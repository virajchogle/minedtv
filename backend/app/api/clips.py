import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, Db, OptionalUser, Urls
from app.config import get_settings
from app.db.models import Clip, Event, Like, Segment, Session, SessionStatus, Transcript, User
from app.schemas import (
    ClipCreate,
    ClipCreatorPackOut,
    ClipDetailOut,
    ClipOut,
    ClipPatch,
    CountsOut,
    CreatorPackOut,
    EventOut,
    ExportOut,
    TranscriptOut,
)
from app.services import counters
from app.services.playlist import build_playlist, validate_clip_range
from app.services.queries import nearest_frame_key
from app.services.redis import get_redis
from app.services.serialize import clip_out
from app.services.storage import get_storage
from app.worker.creator_pack import pack_key, pack_status_key
from app.worker.enqueue import enqueue_creator_pack, enqueue_export
from app.worker.export import export_key, status_key

router = APIRouter(prefix="/clips", tags=["clips"])

HLS_MEDIA_TYPE = "application/vnd.apple.mpegurl"


async def _load(db, clip_id: uuid.UUID) -> tuple[Clip, Session, User]:
    row = (
        await db.execute(
            select(Clip, Session, User)
            .join(Session, Session.id == Clip.session_id)
            .join(User, User.id == Clip.user_id)
            .where(Clip.id == clip_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Clip not found")
    return row.Clip, row.Session, row.User


async def _liked(db, user: User | None, clip_ids: list[uuid.UUID]) -> set[uuid.UUID] | None:
    if user is None:
        return None
    rows = await db.scalars(select(Like.clip_id).where(Like.user_id == user.id, Like.clip_id.in_(clip_ids)))
    return set(rows)


async def _clip_out(db, clip, session, user, urls, me) -> ClipOut:
    pending = (await counters.pending([clip.id]))[clip.id]
    return clip_out(clip, session, user, urls, pending, await _liked(db, me, [clip.id]))


@router.get("/{clip_id}", response_model=ClipDetailOut)
async def get_clip(clip_id: uuid.UUID, db: Db, urls: Urls, me: OptionalUser) -> ClipDetailOut:
    """Clip detail, with the highlight events and transcript lines inside its time range."""
    clip, session, user = await _load(db, clip_id)
    events = (
        await db.scalars(
            select(Event)
            .where(Event.session_id == session.id, Event.t_ms >= clip.start_ms, Event.t_ms <= clip.end_ms)
            .order_by(Event.t_ms)
        )
    ).all()
    transcript = (
        await db.scalars(
            select(Transcript)
            .where(
                Transcript.session_id == session.id,
                Transcript.start_ms < clip.end_ms,
                Transcript.end_ms > clip.start_ms,
            )
            .order_by(Transcript.start_ms)
        )
    ).all()
    base = await _clip_out(db, clip, session, user, urls, me)
    return ClipDetailOut(
        **base.model_dump(),
        session_duration_ms=session.duration_ms,
        events=[
            EventOut(id=e.id, t_ms=e.t_ms, type=e.type, score=e.score, source=e.source, metadata=e.metadata_ or {})
            for e in events
        ],
        transcript=[TranscriptOut.model_validate(t) for t in transcript],
    )


@router.get("/{clip_id}/playlist.m3u8", response_class=PlainTextResponse)
async def clip_playlist(clip_id: uuid.UUID, db: Db):
    """HLS playlist built from the session segments covering start_ms..end_ms."""
    clip, session, _ = await _load(db, clip_id)
    segments = (
        await db.scalars(
            select(Segment)
            .where(
                Segment.session_id == session.id,
                Segment.start_ms < clip.end_ms,
                Segment.start_ms + Segment.duration_ms > clip.start_ms,
            )
            .order_by(Segment.idx)
        )
    ).all()
    if not segments:
        raise HTTPException(409, "Session has no segments yet")
    body = build_playlist(segments, clip.start_ms, clip.end_ms, get_storage().url_for)
    return PlainTextResponse(body, media_type=HLS_MEDIA_TYPE, headers={"Cache-Control": "private, max-age=60"})


@router.post("", response_model=ClipOut, status_code=201)
async def create_clip(body: ClipCreate, user: CurrentUser, db: Db, urls: Urls) -> ClipOut:
    """Create a clip from any time range of a ready session. No video is copied."""
    session = await db.get(Session, body.session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    if session.status != SessionStatus.READY:
        raise HTTPException(409, "Session is not ready")
    try:
        validate_clip_range(body.start_ms, body.end_ms, session.duration_ms)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    clip = Clip(
        session_id=session.id,
        user_id=user.id,
        title=body.title or session.title,
        start_ms=body.start_ms,
        end_ms=body.end_ms,
        thumbnail_key=await nearest_frame_key(db, session.id, (body.start_ms + body.end_ms) // 2),
        status="ready",
        kind="user",
    )
    db.add(clip)
    await db.commit()
    await db.refresh(clip)
    owner = await db.get(User, clip.user_id)
    return await _clip_out(db, clip, session, owner, urls, user)


@router.patch("/{clip_id}", response_model=ClipOut)
async def update_clip(clip_id: uuid.UUID, body: ClipPatch, user: CurrentUser, db: Db, urls: Urls) -> ClipOut:
    """Rename, or extend/trim by moving start_ms and end_ms anywhere within the session."""
    clip, session, owner = await _load(db, clip_id)
    if clip.user_id != user.id:
        raise HTTPException(403, "Not your clip")
    start = body.start_ms if body.start_ms is not None else clip.start_ms
    end = body.end_ms if body.end_ms is not None else clip.end_ms
    try:
        validate_clip_range(start, end, session.duration_ms)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if (start, end) != (clip.start_ms, clip.end_ms):
        clip.start_ms, clip.end_ms = start, end
        clip.thumbnail_key = await nearest_frame_key(db, session.id, (start + end) // 2) or clip.thumbnail_key
    if body.title is not None:
        clip.title = body.title
    await db.commit()
    return await _clip_out(db, clip, session, owner, urls, user)


async def _counts(db, clip: Clip, me: User | None) -> CountsOut:
    views, likes = (await counters.pending([clip.id]))[clip.id]
    liked = await _liked(db, me, [clip.id])
    return CountsOut(
        clip_id=clip.id,
        view_count=clip.view_count + views,
        like_count=clip.like_count + likes,
        liked_by_me=None if liked is None else clip.id in liked,
    )


@router.post("/{clip_id}/like", response_model=CountsOut)
async def like(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> CountsOut:
    clip, _, _ = await _load(db, clip_id)
    inserted = await db.execute(
        pg_insert(Like).values(user_id=user.id, clip_id=clip.id).on_conflict_do_nothing().returning(Like.clip_id)
    )
    if inserted.first() is not None:
        await db.commit()
        await counters.incr_like(clip.id, 1)
    return await _counts(db, clip, user)


@router.delete("/{clip_id}/like", response_model=CountsOut)
async def unlike(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> CountsOut:
    clip, _, _ = await _load(db, clip_id)
    deleted = await db.execute(
        delete(Like).where(Like.user_id == user.id, Like.clip_id == clip.id).returning(Like.clip_id)
    )
    if deleted.first() is not None:
        await db.commit()
        await counters.incr_like(clip.id, -1)
    return await _counts(db, clip, user)


@router.post("/{clip_id}/view", response_model=CountsOut)
async def view(clip_id: uuid.UUID, db: Db, me: OptionalUser) -> CountsOut:
    clip, _, _ = await _load(db, clip_id)
    await counters.incr_view(clip.id)
    return await _counts(db, clip, me)


@router.delete("/{clip_id}", status_code=204)
async def delete_clip(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> Response:
    clip, _, _ = await _load(db, clip_id)
    if clip.user_id != user.id:
        raise HTTPException(403, "Not your clip")
    await db.delete(clip)
    await db.commit()
    return Response(status_code=204)



async def _export_state(clip: Clip) -> ExportOut:
    key = export_key(clip.id, clip.start_ms, clip.end_ms)
    base = dict(clip_id=clip.id, start_ms=clip.start_ms, end_ms=clip.end_ms)
    if await asyncio.to_thread(get_storage().exists, key):
        return ExportOut(**base, status="ready", url=get_storage().url_for(key))
    raw = await get_redis().get(status_key(clip.id, clip.start_ms, clip.end_ms))
    if raw is None:
        return ExportOut(**base, status="none", url=None)
    if raw.startswith("failed"):
        return ExportOut(**base, status="failed", url=None, error=raw.partition(":")[2] or None)
    return ExportOut(**base, status="processing", url=None)


@router.get("/{clip_id}/export", response_model=ExportOut)
async def get_export(clip_id: uuid.UUID, db: Db) -> ExportOut:
    """Status of the MP4 export for the clip's current range."""
    clip, _, _ = await _load(db, clip_id)
    return await _export_state(clip)


@router.post("/{clip_id}/export", response_model=ExportOut, status_code=202)
async def start_export(clip_id: uuid.UUID, db: Db) -> ExportOut:
    """Render the clip as an MP4 (for TikTok/Reels). Idempotent: returns the existing export if
    it's ready or in progress. Poll GET until status is 'ready', then download `url`."""
    clip, _, _ = await _load(db, clip_id)
    state = await _export_state(clip)
    if state.status in ("ready", "processing"):
        return state
    await get_redis().set(status_key(clip.id, clip.start_ms, clip.end_ms), "processing", ex=6 * 3600)
    await run_in_threadpool(enqueue_export, clip.id)
    return state.model_copy(update={"status": "processing", "error": None})


async def _pack_state(clip: Clip) -> ClipCreatorPackOut:
    key = pack_key(clip.id, clip.start_ms, clip.end_ms)
    base = dict(clip_id=clip.id, start_ms=clip.start_ms, end_ms=clip.end_ms)
    storage = get_storage()
    if await asyncio.to_thread(storage.exists, key):
        body = json.loads(await asyncio.to_thread(storage.get_bytes, key))
        return ClipCreatorPackOut(
            **base, status="ready", model=body.get("model"), pack=CreatorPackOut.model_validate(body["pack"])
        )
    raw = await get_redis().get(pack_status_key(clip.id, clip.start_ms, clip.end_ms))
    if raw is None:
        return ClipCreatorPackOut(**base, status="none")
    if raw.startswith("failed"):
        return ClipCreatorPackOut(**base, status="failed", error=raw.partition(":")[2] or None)
    return ClipCreatorPackOut(**base, status="processing")


@router.get("/{clip_id}/creator-pack", response_model=ClipCreatorPackOut)
async def get_creator_pack(clip_id: uuid.UUID, db: Db) -> ClipCreatorPackOut:
    """Status of the AI creator pack (titles, caption, hashtags, YouTube/Reddit metadata) for this clip."""
    clip, _, _ = await _load(db, clip_id)
    return await _pack_state(clip)


@router.post("/{clip_id}/creator-pack", response_model=ClipCreatorPackOut, status_code=202)
async def start_creator_pack(clip_id: uuid.UUID, db: Db) -> ClipCreatorPackOut:
    """Generate the creator pack for an already-uploaded clip (no re-upload). Gemini watches the
    clip's MP4; takes ~1-2 min. Idempotent; poll GET until status is 'ready'."""
    if not get_settings().gemini_api_key:
        raise HTTPException(503, "Creator packs are not configured (GEMINI_API_KEY missing)")
    clip, _, _ = await _load(db, clip_id)
    state = await _pack_state(clip)
    if state.status in ("ready", "processing"):
        return state
    await get_redis().set(pack_status_key(clip.id, clip.start_ms, clip.end_ms), "processing", ex=6 * 3600)
    await run_in_threadpool(enqueue_creator_pack, clip.id)
    return state.model_copy(update={"status": "processing", "error": None})
