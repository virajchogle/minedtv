import asyncio
import uuid

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, Db, Urls
from app.config import get_settings
from app.db.models import (
    PIPELINE_STEPS,
    Clip,
    Frame,
    FrameHighlightRun,
    FrameViralityScore,
    Segment,
    Session,
    SessionStatus,
    User,
)
from app.db.session import get_sessionmaker
from app.schemas import FrameHighlightsCreate, FrameHighlightsOut, FrameViralityPoint, SessionOut, SessionStatusEvent
from app.services.playlist import build_playlist
from app.services.frame_virality import ALGORITHM_VERSION
from app.services.serialize import clip_out, session_out, url_or_none
from app.services.storage import get_storage
from app.worker.enqueue import enqueue_frame_highlights, enqueue_pipeline

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
        moderation_violations=s.moderation_violations,
    )


async def _get_session(db, session_id: uuid.UUID) -> Session:
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    return session


async def _frame_highlights_out(db, session: Session, owner: User, urls: Urls) -> FrameHighlightsOut:
    settings = get_settings()
    run = await db.get(FrameHighlightRun, session.id)
    if run is None:
        return FrameHighlightsOut(
            session_id=session.id,
            status="none",
            requested_count=settings.frame_highlight_count,
            clip_duration_ms=settings.frame_highlight_duration_ms,
            algorithm_version=ALGORITHM_VERSION,
        )

    scores: list[FrameViralityPoint] = []
    clips = []
    if run.status == "ready":
        rows = (
            await db.execute(
                select(FrameViralityScore, Frame.thumbnail_key)
                .join(Frame, Frame.id == FrameViralityScore.frame_id)
                .where(FrameViralityScore.session_id == session.id)
                .order_by(FrameViralityScore.t_ms)
            )
        ).all()
        scores = [
            FrameViralityPoint(
                frame_id=score.frame_id,
                t_ms=score.t_ms,
                score=score.score,
                visual_score=score.visual_score,
                novelty_score=score.novelty_score,
                event_score=score.event_score,
                speech_score=score.speech_score,
                visibility_score=score.visibility_score,
                scene_score=score.scene_score,
                selected=score.selected,
                thumbnail_url=url_or_none(thumbnail_key),
            )
            for score, thumbnail_key in rows
        ]
        clip_rows = (
            await db.scalars(
                select(Clip)
                .where(Clip.session_id == session.id, Clip.generation_source == "frame_virality")
                .order_by(Clip.start_ms)
            )
        ).all()
        clips = [clip_out(clip, session, owner, urls) for clip in clip_rows]

    return FrameHighlightsOut(
        session_id=session.id,
        status=run.status,
        requested_count=run.requested_count,
        clip_duration_ms=run.clip_duration_ms,
        algorithm_version=run.algorithm_version,
        error=run.error,
        scores=scores,
        clips=clips,
        updated_at=run.updated_at,
    )


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, db: Db, urls: Urls) -> SessionOut:
    session = await _get_session(db, session_id)
    user = await db.get(User, session.user_id)
    return session_out(session, user, urls)


@router.post("/{session_id}/frame-highlights", response_model=FrameHighlightsOut, status_code=202)
async def create_frame_highlights(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: Db,
    urls: Urls,
    body: FrameHighlightsCreate = Body(default=FrameHighlightsCreate()),
) -> FrameHighlightsOut:
    """Score existing sampled frames and generate private highlight clips. This is on-demand and
    does not decode the video again. Poll the matching GET until status is ready or failed."""
    session = await _get_session(db, session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session")
    if session.status != SessionStatus.READY:
        raise HTTPException(409, f"Session is {session.status}; frame highlights require a ready session")

    settings = get_settings()
    count = body.count or settings.frame_highlight_count
    clip_duration_ms = body.clip_duration_ms or settings.frame_highlight_duration_ms
    run = await db.get(FrameHighlightRun, session.id)
    if run is not None and run.status == "processing":
        return await _frame_highlights_out(db, session, user, urls)
    if (
        run is not None
        and run.status == "ready"
        and run.requested_count == count
        and run.clip_duration_ms == clip_duration_ms
        and run.algorithm_version == ALGORITHM_VERSION
    ):
        return await _frame_highlights_out(db, session, user, urls)

    if run is None:
        run = FrameHighlightRun(
            session_id=session.id,
            status="processing",
            requested_count=count,
            clip_duration_ms=clip_duration_ms,
            algorithm_version=ALGORITHM_VERSION,
        )
        db.add(run)
    else:
        run.status = "processing"
        run.requested_count = count
        run.clip_duration_ms = clip_duration_ms
        run.algorithm_version = ALGORITHM_VERSION
        run.error = None
    await db.commit()
    await db.refresh(run)
    try:
        await run_in_threadpool(enqueue_frame_highlights, session.id, count, clip_duration_ms)
    except Exception as error:
        run.status = "failed"
        run.error = f"QueueError: {error}"[:1000]
        await db.commit()
        raise HTTPException(503, "Could not queue frame highlight analysis") from error
    return await _frame_highlights_out(db, session, user, urls)


@router.get("/{session_id}/frame-highlights", response_model=FrameHighlightsOut)
async def get_frame_highlights(
    session_id: uuid.UUID, user: CurrentUser, db: Db, urls: Urls
) -> FrameHighlightsOut:
    """Return frame scores and generated clips for the current frame-highlight run."""
    session = await _get_session(db, session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session")
    return await _frame_highlights_out(db, session, user, urls)


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
