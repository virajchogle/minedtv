"""Connect a YouTube channel and post clips from the "ready to post" bucket."""

import asyncio
import html
import json
import logging
import uuid
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, Db, UrlBuilder
from app.config import get_settings
from app.db.models import Clip, YouTubeAccount, YouTubeUpload, YouTubeUploadStatus
from app.schemas import YouTubeConnectOut, YouTubePostIn, YouTubeStatusOut, YouTubeUploadOut
from app.services import youtube
from app.services.storage import get_storage
from app.worker.creator_pack import pack_key
from app.worker.clip_highlights import highlight_result_key
from app.worker.enqueue import enqueue_youtube_post

router = APIRouter(tags=["youtube"])
log = logging.getLogger(__name__)

POSTABLE_STATES = ("ready", "published")


def _redirect_uri(request: Request) -> str:
    return get_settings().youtube_redirect_uri or f"{UrlBuilder(request).base}/youtube/callback"


def _require_configured() -> None:
    if not youtube.is_configured(get_settings()):
        raise HTTPException(503, "YouTube posting isn't configured on this server yet")


def _upload_out(u: YouTubeUpload) -> YouTubeUploadOut:
    return YouTubeUploadOut(
        id=u.id,
        clip_id=u.clip_id,
        kind=u.kind,
        status=u.status,
        privacy=u.privacy,
        title=u.title,
        description=u.description,
        tags=list(u.tags or []),
        video_id=u.video_id,
        url=youtube.video_url(u.video_id) if u.video_id else None,
        error=u.error,
        created_at=u.created_at,
        updated_at=u.updated_at,
    )


# ---------------------------------------------------------------- connection


@router.get("/youtube/status", response_model=YouTubeStatusOut)
async def youtube_status(me: CurrentUser, db: Db) -> YouTubeStatusOut:
    account = await db.get(YouTubeAccount, me.id)
    return YouTubeStatusOut(
        configured=youtube.is_configured(get_settings()),
        connected=account is not None,
        channel_id=account.channel_id if account else None,
        channel_title=account.channel_title if account else None,
    )


@router.get("/youtube/connect", response_model=YouTubeConnectOut)
async def youtube_connect(me: CurrentUser, request: Request) -> YouTubeConnectOut:
    """Start connecting the acting user's YouTube channel: open `auth_url` in a browser."""
    _require_configured()
    settings = get_settings()
    return YouTubeConnectOut(auth_url=youtube.auth_url(settings, _redirect_uri(request), youtube.sign_state(settings, me.id)))


def _finish_page(ok: bool, message: str) -> HTMLResponse | RedirectResponse:
    frontend = get_settings().frontend_url
    if frontend:
        query = "youtube=connected" if ok else f"youtube=error&message={quote(message[:300])}"
        return RedirectResponse(f"{frontend.rstrip('/')}/library?{query}", status_code=303)
    title = "YouTube connected" if ok else "Couldn't connect YouTube"
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>{title}</title>"
        f"<body style='font-family:system-ui;background:#0b0b0c;color:#eee;display:grid;place-items:center;height:100vh'>"
        f"<div style='text-align:center'><h2>{html.escape(title)}</h2><p>{html.escape(message)}</p>"
        f"<p style='opacity:.6'>You can close this tab.</p></div>",
        status_code=200 if ok else 400,
    )


@router.get("/youtube/callback", include_in_schema=False)
async def youtube_callback(
    request: Request,
    db: Db,
    code: str | None = None,
    state: str | None = None,
    error: str | None = Query(default=None),
):
    """Google redirects here after the user approves. Open path (browsers can't send X-API-Key);
    the signed `state` ties it to the user who started the flow."""
    settings = get_settings()
    if error:
        return _finish_page(False, f"Google said: {error}")
    if not code or not state:
        return _finish_page(False, "Missing code or state")
    try:
        user_id = youtube.verify_state(settings, state)
        async with httpx.AsyncClient(timeout=30) as client:
            tokens = await youtube.exchange_code(client, settings, code, _redirect_uri(request))
            refresh = tokens.get("refresh_token")
            if not refresh:
                raise youtube.YouTubeError("Google didn't return a refresh token; remove the app's access and try again")
            channel_id, channel_title = await youtube.my_channel(client, tokens["access_token"])
    except youtube.YouTubeError as e:
        log.warning("youtube connect failed", extra={"error": str(e)})
        return _finish_page(False, str(e))

    values = dict(
        user_id=user_id,
        channel_id=channel_id,
        channel_title=channel_title,
        refresh_token_enc=youtube.encrypt_token(settings, refresh),
        scopes=tokens.get("scope", ""),
    )
    await db.execute(
        pg_insert(YouTubeAccount)
        .values(**values)
        .on_conflict_do_update(index_elements=[YouTubeAccount.user_id], set_={k: v for k, v in values.items() if k != "user_id"})
    )
    await db.commit()
    log.info("youtube connected", extra={"user_id": str(user_id), "channel_id": channel_id})
    return _finish_page(True, f"Clips can now be posted to {channel_title or 'your channel'}.")


@router.delete("/youtube/connection", response_model=YouTubeStatusOut)
async def youtube_disconnect(me: CurrentUser, db: Db) -> YouTubeStatusOut:
    """Disconnect: revokes the token with Google and forgets it."""
    account = await db.get(YouTubeAccount, me.id)
    if account is not None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await youtube.revoke(client, youtube.decrypt_token(get_settings(), account.refresh_token_enc))
        except Exception:  # noqa: BLE001 - forgetting it locally still disconnects
            log.warning("youtube revoke failed", exc_info=True)
        await db.execute(delete(YouTubeAccount).where(YouTubeAccount.user_id == me.id))
        await db.commit()
    return YouTubeStatusOut(configured=youtube.is_configured(get_settings()), connected=False)


# ---------------------------------------------------------------- posting


async def _pack_defaults(clip: Clip) -> tuple[str | None, str | None, list[str]]:
    """YouTube title/description/tags from the clip's AI creator pack, if one was generated."""
    storage = get_storage()
    key = pack_key(clip.id, clip.start_ms, clip.end_ms)
    try:
        if not await asyncio.to_thread(storage.exists, key):
            return None, None, []
        yt = json.loads(await asyncio.to_thread(storage.get_bytes, key))["pack"]["youtube"]
        return yt.get("title"), yt.get("description"), list(yt.get("tags") or [])
    except Exception:  # noqa: BLE001 - defaults are a convenience
        log.warning("couldn't read creator pack for youtube defaults", exc_info=True)
        return None, None, []


@router.post("/clips/{clip_id}/youtube", response_model=YouTubeUploadOut, status_code=202)
async def post_clip_to_youtube(clip_id: uuid.UUID, body: YouTubePostIn, me: CurrentUser, db: Db) -> YouTubeUploadOut:
    """Post a clip from the "ready to post" bucket (or an already published clip) to your YouTube
    channel. Title/description/tags default to the AI creator pack's YouTube metadata. Runs in the
    worker (about 1-2 minutes); poll GET /clips/{id}/youtube."""
    _require_configured()
    clip = await db.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    if clip.user_id != me.id:
        raise HTTPException(403, "Not your clip")
    if clip.publish_state not in POSTABLE_STATES:
        raise HTTPException(409, "Mark the clip ready to post first")
    if await db.get(YouTubeAccount, me.id) is None:
        raise HTTPException(409, "Connect your YouTube channel first (GET /youtube/connect)")

    in_flight = await db.scalar(
        select(YouTubeUpload)
        .where(
            YouTubeUpload.clip_id == clip.id,
            YouTubeUpload.status.in_((YouTubeUploadStatus.QUEUED, YouTubeUploadStatus.UPLOADING)),
        )
        .limit(1)
    )
    if in_flight is not None:
        return _upload_out(in_flight)

    kind, source_key = "clip", None
    if body.montage is not None:
        manifest_key = highlight_result_key(clip.id, clip.start_ms, clip.end_ms, body.montage)
        storage = get_storage()
        if not await asyncio.to_thread(storage.exists, manifest_key):
            raise HTTPException(409, "Make the montage first (POST /clips/{id}/highlights), then post it")
        manifest = json.loads(await asyncio.to_thread(storage.get_bytes, manifest_key))
        kind, source_key = "montage", manifest["video_key"]
        if body.description is None and manifest.get("suggested_caption"):
            hashtags = " ".join(f"#{h.lstrip('#')}" for h in manifest.get("hashtags") or [])
            body = body.model_copy(update={"description": f"{manifest['suggested_caption']}\n\n{hashtags}".strip()})

    title, description, tags = body.title, body.description, body.tags
    if title is None or description is None or tags is None:
        p_title, p_desc, p_tags = await _pack_defaults(clip)
        title = title if title is not None else (p_title or clip.title or "MinedIt clip")
        description = description if description is not None else (p_desc or f"{clip.title or 'Gameplay clip'}\n\nClipped with MinedIt")
        tags = tags if tags is not None else p_tags
    title, description, tags = youtube.clean_metadata(title, description, tags)

    up = YouTubeUpload(
        clip_id=clip.id, user_id=me.id, privacy=body.privacy, title=title, description=description, tags=tags,
        kind=kind, source_key=source_key,
    )
    db.add(up)
    await db.commit()
    await db.refresh(up)
    await run_in_threadpool(enqueue_youtube_post, up.id)
    return _upload_out(up)


@router.get("/clips/{clip_id}/youtube", response_model=list[YouTubeUploadOut])
async def clip_youtube_uploads(clip_id: uuid.UUID, me: CurrentUser, db: Db) -> list[YouTubeUploadOut]:
    """Your YouTube posts of this clip, newest first."""
    rows = await db.scalars(
        select(YouTubeUpload)
        .where(YouTubeUpload.clip_id == clip_id, YouTubeUpload.user_id == me.id)
        .order_by(YouTubeUpload.created_at.desc())
    )
    return [_upload_out(u) for u in rows]
