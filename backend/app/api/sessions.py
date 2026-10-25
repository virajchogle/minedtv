import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, Db, Urls
from app.db.models import PIPELINE_STEPS, Segment, Session, SessionStatus, User
from app.db.session import get_sessionmaker
from app.schemas import SessionOut, SessionStatusEvent
from app.services.playlist import build_playlist
from app.services.serialize import session_out
from app.services.storage import get_storage
from app.worker.enqueue import enqueue_pipeline

router = APIRouter(prefix="/sessions", tags=["sessions"])

HLS_MEDIA_TYPE = "application/vnd.apple.mpegurl"
_TERMINAL = {SessionStatus.READY, SessionStatus.FAILED, SessionStatus.BLOCKED}


def status_event(s: Session) -> SessionStatusEvent:
    done_steps = PIPELINE_STEPS.index(s.last_step) + 1 if s.last_step in PIPELINE_STEPS else 0
    return SessionStatusEvent(
        session_id=s.id,
        status=s.status,
        progress=1.0 if s.status == SessionStatus.READY else done_steps / len(PIPELINE_STEPS),
        steps=PIPELINE_STEPS,
        last_step=s.last_step,
        failed_step=s.failed_step,
        error=s.error,
        done=s.status in _TERMINAL,
        moderation_severity=s.moderation_severity,
        age_restricted=s.age_restricted,
    )


async def _get_session(db, session_id: uuid.UUID) -> Session:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, db: Db, urls: Urls) -> SessionOut:
    session = await _get_session(db, session_id)
    user = await db.get(User, session.user_id)
    return session_out(session, user, urls)


@router.get(
    "/{session_id}/status",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE stream of `status` events (SessionStatusEvent JSON)"}},
)
async def stream_status(session_id: uuid.UUID, request: Request, db: Db):
    """Server-sent events: one `status` event whenever processing progresses; closes when ready or failed."""
    await _get_session(db, session_id)

    async def events():
        last_payload = None
        idle = 0.0
        while True:
            if await request.is_disconnected():
                return
            async with get_sessionmaker()() as poll_db:
                s = await poll_db.get(Session, session_id)
            if s is None:
                return
            ev = status_event(s)
            payload = ev.model_dump_json()
            if payload != last_payload:
                yield f"event: status\ndata: {payload}\n\n"
                last_payload = payload
                idle = 0.0
            elif idle >= 15:
                yield ": keep-alive\n\n"
                idle = 0.0
            if ev.done:
                return
            await asyncio.sleep(1)
            idle += 1

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/{session_id}/reprocess", response_model=SessionStatusEvent, status_code=202)
async def reprocess(session_id: uuid.UUID, user: CurrentUser, db: Db) -> SessionStatusEvent:
    """Retry processing, resuming after the last step that completed."""
    session = await _get_session(db, session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session")
    if session.status not in (SessionStatus.FAILED, SessionStatus.READY):
        raise HTTPException(409, f"Session is {session.status}; only failed or ready sessions can be reprocessed")
    resume = session.status == SessionStatus.FAILED
    if not resume:
        session.last_step = None
    session.status = SessionStatus.QUEUED
    session.error = None
    await db.commit()
    await run_in_threadpool(enqueue_pipeline, session.id, resume)
    return status_event(session)


@router.get("/{session_id}/playlist.m3u8", response_class=PlainTextResponse)
async def session_playlist(
    session_id: uuid.UUID,
    db: Db,
    start_ms: int | None = Query(default=None, ge=0),
    end_ms: int | None = Query(default=None, gt=0),
):
    """HLS playlist for the whole session, or for an arbitrary range (used by search's suggested windows)."""
    session = await _get_session(db, session_id)
    if session.status != SessionStatus.READY or not session.duration_ms:
        raise HTTPException(409, "Session is not ready")
    start = start_ms or 0
    end = min(end_ms or session.duration_ms, session.duration_ms)
    if end <= start:
        raise HTTPException(422, "end_ms must be greater than start_ms")
    segments = (
        await db.scalars(
            select(Segment)
            .where(Segment.session_id == session_id, Segment.start_ms < end, Segment.start_ms + Segment.duration_ms > start)
            .order_by(Segment.idx)
        )
    ).all()
    body = build_playlist(segments, start, end, get_storage().url_for)
    return PlainTextResponse(body, media_type=HLS_MEDIA_TYPE, headers={"Cache-Control": "private, max-age=60"})
