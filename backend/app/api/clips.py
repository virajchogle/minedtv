import asyncio
import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, Db, OptionalUser, Urls
from app.config import get_settings
from app.db.models import (
    Clip,
    Event,
    Frame,
    Like,
    NotificationType,
    Segment,
    Session,
    SessionStatus,
    Transcript,
    User,
)
from app.schemas import (
    ClipCreate,
    ClipCreatorPackOut,
    ClipHighlightsIn,
    ClipHighlightsOut,
    ClipViralityOut,
    ClipDetailOut,
    ClipOut,
    ClipPatch,
    CountsOut,
    CreatorPackOut,
    EventOut,
    ExportOut,
    TranscriptOut,
)
from app.services import counters, youtube
from app.services.playlist import build_playlist, validate_clip_range
from app.services.queries import nearest_frame_key
from app.services.redis import get_redis
from app.services.serialize import clip_out
from app.services.clip_virality import clip_virality
from app.services.social import comment_counts, notify
from app.services.storage import get_storage
from app.worker.creator_pack import pack_key, pack_status_key
from app.worker.enqueue import enqueue_clip_highlights, enqueue_creator_pack, enqueue_export, enqueue_frame_highlights
from app.worker.export import export_key, status_key
from app.worker.clip_highlights import (
    highlight_result_key,
    highlight_status_key,
    status_payload as highlight_status_payload,
)

router = APIRouter(prefix="/clips", tags=["clips"])
log = logging.getLogger(__name__)

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


def _check_visible(clip: Clip, me: User | None) -> None:
    """Unpublished clips (draft / ready) exist only for their owner; everyone else gets a 404."""
    if clip.publish_state != "published" and (me is None or me.id != clip.user_id):
        raise HTTPException(404, "Clip not found")


def _check_age(clip: Clip, me: User | None) -> None:
    """Age-restricted clips are visible to their owner regardless of the owner's own age
    (so uploaders can see what they posted), but otherwise need a signed-in adult account."""
    is_owner = me is not None and me.id == clip.user_id
    if clip.age_restricted and not is_owner and not (me is not None and me.is_adult):
        raise HTTPException(403, "This clip is restricted to users 18 and older")


async def _liked(db, user: User | None, clip_ids: list[uuid.UUID]) -> set[uuid.UUID] | None:
    if user is None:
        return None
    rows = await db.scalars(select(Like.clip_id).where(Like.user_id == user.id, Like.clip_id.in_(clip_ids)))
    return set(rows)


async def _clip_out(db, clip, session, user, urls, me) -> ClipOut:
    pending = (await counters.pending([clip.id]))[clip.id]
    comments = (await comment_counts(db, [clip.id]))[clip.id]
    on_youtube = (await youtube.posted_urls(db, [clip.id])).get(clip.id)
    return clip_out(clip, session, user, urls, pending, await _liked(db, me, [clip.id]), comments, on_youtube)


@router.get("/{clip_id}", response_model=ClipDetailOut)
async def get_clip(clip_id: uuid.UUID, db: Db, urls: Urls, me: OptionalUser) -> ClipDetailOut:
    """Clip detail, with the highlight events and transcript lines inside its time range.
    Unpublished clips are only visible to their owner (send X-User-Id)."""
    clip, session, user = await _load(db, clip_id)
    _check_visible(clip, me)
    _check_age(clip, me)
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
    frame_count = await db.scalar(
        select(func.count())
        .select_from(Frame)
        .where(Frame.session_id == session.id, Frame.t_ms >= clip.start_ms, Frame.t_ms < clip.end_ms)
    )
    base = await _clip_out(db, clip, session, user, urls, me)
    return ClipDetailOut(
        **base.model_dump(),
        session_duration_ms=session.duration_ms,
        frame_count=frame_count or 0,
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
    """Create a clip from any time range of a ready session. No video is copied. New clips start
    as drafts (owner-only); publish them with POST /clips/{id}/publish."""
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
        age_restricted=session.age_restricted,
        moderation_violations=session.moderation_violations,
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
    _check_visible(clip, user)
    inserted = await db.execute(
        pg_insert(Like).values(user_id=user.id, clip_id=clip.id).on_conflict_do_nothing().returning(Like.clip_id)
    )
    if inserted.first() is not None:
        await notify(db, user_id=clip.user_id, actor_id=user.id, type=NotificationType.LIKE, clip_id=clip.id, once=True)
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


def _viewer_key(request: Request, me: User | None, viewer_id: str | None) -> str:
    """Who's watching, for de-duplicating views: the user, else the client's anonymous viewer ID,
    else its IP address (the first X-Forwarded-For hop on Cloud Run)."""
    if me is not None:
        return f"user:{me.id}"
    if viewer_id:
        return f"anon:{viewer_id.strip()[:64]}"
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"ip:{ip}"


@router.post("/{clip_id}/view", response_model=CountsOut)
async def view(
    clip_id: uuid.UUID,
    request: Request,
    db: Db,
    me: OptionalUser,
    x_viewer_id: Annotated[
        str | None, Header(description="Stable anonymous ID for a signed-out viewer (one per browser or install)")
    ] = None,
) -> CountsOut:
    """Count a view. Repeat views by the same viewer within VIEW_DEDUP_MINUTES count once, and
    owners watching their own clips don't count."""
    clip, _, _ = await _load(db, clip_id)
    _check_visible(clip, me)
    if me is None or me.id != clip.user_id:
        await counters.incr_view(
            clip.id, _viewer_key(request, me, x_viewer_id), get_settings().view_dedup_minutes * 60
        )
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
async def get_export(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> ExportOut:
    """Status of the MP4 export for the clip's current range (owner only)."""
    clip = await _load_owned(db, clip_id, user)
    return await _export_state(clip)


@router.post("/{clip_id}/export", response_model=ExportOut, status_code=202)
async def start_export(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> ExportOut:
    """Render the clip as an MP4 (for TikTok/Reels; owner only). Idempotent: returns the existing
    export if it's ready or in progress. Poll GET until status is 'ready', then download `url`."""
    clip = await _load_owned(db, clip_id, user)
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
async def get_creator_pack(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> ClipCreatorPackOut:
    """Status of the AI creator pack (titles, caption, hashtags, YouTube/Reddit metadata) for this
    clip. Owner only."""
    clip = await _load_owned(db, clip_id, user)
    return await _pack_state(clip)


@router.post("/{clip_id}/creator-pack", response_model=ClipCreatorPackOut, status_code=202)
async def start_creator_pack(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> ClipCreatorPackOut:
    """Generate the creator pack for a clip you own (no re-upload). Gemini watches the clip's MP4;
    takes ~1-2 min. Idempotent; poll GET until status is 'ready'."""
    clip = await _load_owned(db, clip_id, user)
    if not get_settings().gemini_api_key:
        raise HTTPException(503, "Creator packs are not configured (GEMINI_API_KEY missing)")
    state = await _pack_state(clip)
    if state.status in ("ready", "processing"):
        return state
    await get_redis().set(pack_status_key(clip.id, clip.start_ms, clip.end_ms), "processing", ex=6 * 3600)
    await run_in_threadpool(enqueue_creator_pack, clip.id)
    return state.model_copy(update={"status": "processing", "error": None})


def _highlight_base(clip: Clip, options: ClipHighlightsIn) -> dict:
    return {
        "clip_id": clip.id,
        "start_ms": clip.start_ms,
        "end_ms": clip.end_ms,
        "platform": options.platform,
        "mode": options.mode,
        "captions_enabled": options.captions,
        "caption_style": options.caption_style,
        "hook_enabled": options.hook,
    }


async def _highlight_state(clip: Clip, options: ClipHighlightsIn) -> ClipHighlightsOut:
    base = _highlight_base(clip, options)
    storage = get_storage()
    result_key = highlight_result_key(clip.id, clip.start_ms, clip.end_ms, options)
    if await asyncio.to_thread(storage.exists, result_key):
        manifest = json.loads(await asyncio.to_thread(storage.get_bytes, result_key))
        video_url = storage.url_for(manifest["video_key"])
        return ClipHighlightsOut(
            **base,
            status="ready",
            stage="rendering",
            progress=1.0,
            error=None,
            algorithm_version=manifest.get("algorithm_version"),
            video_url=video_url,
            download_url=video_url,
            width=manifest.get("width"),
            height=manifest.get("height"),
            duration_ms=manifest.get("duration_ms"),
            frames_analyzed=manifest.get("frames_analyzed", 0),
            captions_burned=manifest.get("captions_burned", False),
            moments=manifest.get("moments", []),
            captions=manifest.get("captions", []),
            summary=manifest.get("summary"),
            suggested_caption=manifest.get("suggested_caption"),
            hashtags=manifest.get("hashtags", []),
        )

    raw = await get_redis().get(highlight_status_key(clip.id, clip.start_ms, clip.end_ms, options))
    if raw is None:
        return ClipHighlightsOut(**base, status="none", stage="queued", progress=0.0)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        state = {
            "status": "failed" if str(raw).startswith("failed") else "processing",
            "stage": "queued",
            "progress": 0.0,
            "error": str(raw).partition(":")[2] or None,
        }
    return ClipHighlightsOut(**base, **state)


@router.post("/{clip_id}/highlights", response_model=ClipHighlightsOut, status_code=202)
async def start_clip_highlights(
    clip_id: uuid.UUID,
    body: ClipHighlightsIn,
    user: CurrentUser,
    db: Db,
) -> ClipHighlightsOut:
    """Start or reuse an asynchronous AI-share render for a stored clip. Owner only."""
    clip = await _load_owned(db, clip_id, user)
    settings = get_settings()
    if clip.end_ms - clip.start_ms > settings.stored_highlight_max_minutes * 60_000:
        raise HTTPException(422, f"Clip exceeds the {settings.stored_highlight_max_minutes}-minute highlight limit")
    cached_pack = pack_key(clip.id, clip.start_ms, clip.end_ms)
    if not settings.gemini_api_key and not await asyncio.to_thread(get_storage().exists, cached_pack):
        raise HTTPException(503, "Stored highlights are not configured (GEMINI_API_KEY missing)")
    state = await _highlight_state(clip, body)
    if state.status in ("ready", "processing"):
        return state
    skey = highlight_status_key(clip.id, clip.start_ms, clip.end_ms, body)
    redis = get_redis()
    queued = highlight_status_payload("processing", "queued", 0.0)
    if state.status == "none":
        claimed = await redis.set(skey, queued, ex=24 * 3600, nx=True)
        if not claimed:
            return await _highlight_state(clip, body)
    else:
        # A POST after failure is an explicit retry for the same cached options.
        await redis.set(skey, queued, ex=24 * 3600)
    try:
        await run_in_threadpool(enqueue_clip_highlights, clip.id, body.model_dump(mode="json"))
    except Exception as exc:
        log.exception("Could not enqueue stored highlight", extra={"clip_id": str(clip.id)})
        await redis.set(
            skey,
            highlight_status_payload("failed", "queued", 0.0, f"{type(exc).__name__}: {exc}"[:500]),
            ex=24 * 3600,
        )
        raise HTTPException(503, "Could not queue highlight generation") from exc
    return state.model_copy(update={"status": "processing", "stage": "queued", "progress": 0.0, "error": None})


@router.get("/{clip_id}/highlights", response_model=ClipHighlightsOut)
async def get_clip_highlights(
    clip_id: uuid.UUID,
    user: CurrentUser,
    db: Db,
    platform: str = "tiktok",
    mode: str = "single",
    captions: bool = True,
    caption_style: str = "bold",
    hook: bool = True,
) -> ClipHighlightsOut:
    """Poll the stored-clip AI-share job using the same options supplied to POST."""
    clip = await _load_owned(db, clip_id, user)
    try:
        options = ClipHighlightsIn(
            platform=platform,
            mode=mode,
            captions=captions,
            caption_style=caption_style,
            hook=hook,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _highlight_state(clip, options)


# ---------------------------------------------------------------- publish state


async def _set_state(clip_id: uuid.UUID, state: str, user: User, db, urls) -> ClipOut:
    clip, session, owner = await _load(db, clip_id)
    if clip.user_id != user.id:
        raise HTTPException(403, "Not your clip")
    if clip.publish_state != state:
        clip.publish_state = state
        clip.published_at = func.now() if state == "published" else None
        await db.commit()
        await db.refresh(clip)
    return await _clip_out(db, clip, session, owner, urls, user)


@router.post("/{clip_id}/publish", response_model=ClipOut)
async def publish_clip(clip_id: uuid.UUID, user: CurrentUser, db: Db, urls: Urls) -> ClipOut:
    """Make the clip public: it appears in the feed, search and the owner's profile."""
    return await _set_state(clip_id, "published", user, db, urls)


@router.post("/{clip_id}/unpublish", response_model=ClipOut)
async def unpublish_clip(clip_id: uuid.UUID, user: CurrentUser, db: Db, urls: Urls) -> ClipOut:
    """Back to draft: hidden from everyone but the owner."""
    return await _set_state(clip_id, "draft", user, db, urls)


@router.post("/{clip_id}/mark-ready", response_model=ClipOut)
async def mark_ready(clip_id: uuid.UUID, user: CurrentUser, db: Db, urls: Urls) -> ClipOut:
    """Queue the clip as "ready to post to YouTube". Still private (owner only) until published."""
    return await _set_state(clip_id, "ready", user, db, urls)


# ---------------------------------------------------------------- virality (frame scorer)


async def _load_owned(db, clip_id: uuid.UUID, user: User) -> Clip:
    clip, _, _ = await _load(db, clip_id)
    if clip.user_id != user.id:
        raise HTTPException(403, "Not your clip")
    return clip


@router.get("/{clip_id}/virality", response_model=ClipViralityOut)
async def get_virality(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> ClipViralityOut:
    """The clip's virality score (0–100), verdict, signal breakdown and per-frame curve, from the
    frame scorer that runs on every upload. Owner only."""
    clip = await _load_owned(db, clip_id, user)
    return await clip_virality(db, clip)


@router.post("/{clip_id}/virality", response_model=ClipViralityOut, status_code=202)
async def score_virality(clip_id: uuid.UUID, user: CurrentUser, db: Db) -> ClipViralityOut:
    """Score the clip's upload if it hasn't been (uploads from before the frame scorer). Leaves
    every clip as it is; takes a few seconds. Poll GET until status is 'ready'."""
    clip = await _load_owned(db, clip_id, user)
    state = await clip_virality(db, clip)
    if state.status in ("ready", "processing"):
        return state
    st = get_settings()
    await run_in_threadpool(
        enqueue_frame_highlights, clip.session_id, st.frame_highlight_count, st.frame_highlight_duration_ms, False
    )
    return state.model_copy(update={"status": "processing", "error": None})
