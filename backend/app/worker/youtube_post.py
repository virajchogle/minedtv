"""Post a clip to its owner's YouTube channel: render the MP4 (reusing the export), refresh
the owner's access token, upload, and record the result. The owner gets a notification
either way."""

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path

import httpx

from app.db.models import NotificationType, YouTubeAccount, YouTubeUpload, YouTubeUploadStatus
from app.services import youtube
from app.services.social import notify
from app.worker.export import export_clip
from app.worker.pipeline import Deps

log = logging.getLogger("youtube")


async def post_to_youtube(upload_id: uuid.UUID | str, deps: Deps, redis=None, http: httpx.AsyncClient | None = None) -> str:
    """Run one queued YouTubeUpload. Returns the YouTube video id."""
    upload_id = uuid.UUID(str(upload_id))
    async with deps.sessionmaker() as db:
        up = await db.get(YouTubeUpload, upload_id)
        if up is None:
            raise LookupError(f"youtube upload {upload_id} not found")
        if up.status == YouTubeUploadStatus.PUBLISHED and up.video_id:
            return up.video_id
        account = await db.get(YouTubeAccount, up.user_id)
        clip_id, user_id, source_key = up.clip_id, up.user_id, up.source_key
        meta = (up.title, up.description, list(up.tags or []), up.privacy)
        up.status, up.error = YouTubeUploadStatus.UPLOADING, None
        await db.commit()

    async def finish(status: str, video_id: str | None = None, error: str | None = None):
        async with deps.sessionmaker() as db:
            row = await db.get(YouTubeUpload, upload_id)
            row.status, row.video_id, row.error = status, video_id, error
            await notify(
                db,
                user_id=user_id,
                type=NotificationType.YOUTUBE_POSTED,
                clip_id=clip_id,
                data={
                    "status": status,
                    "video_id": video_id,
                    "url": youtube.video_url(video_id) if video_id else None,
                    "privacy": meta[3],
                    "title": meta[0],
                    "error": error,
                },
            )
            await db.commit()

    workdir = Path(tempfile.mkdtemp(prefix=f"minedtv-yt-{upload_id}-"))
    own_client = http is None
    client = http or httpx.AsyncClient(timeout=httpx.Timeout(60))
    try:
        if account is None:
            raise youtube.YouTubeError("YouTube isn't connected for this user")
        # A montage post uploads its rendered file; otherwise the clip's own MP4 export.
        mp4_key = source_key or await export_clip(clip_id, deps, redis)
        mp4 = workdir / "clip.mp4"
        await asyncio.to_thread(deps.storage.download_file, mp4_key, mp4)
        token = await youtube.access_token(client, deps.settings, youtube.decrypt_token(deps.settings, account.refresh_token_enc))
        title, description, tags = youtube.clean_metadata(*meta[:3])
        video_id = await youtube.upload_video(client, token, mp4, title, description, tags, meta[3])
        await finish(YouTubeUploadStatus.PUBLISHED, video_id=video_id)
        log.info("posted to youtube", extra={"clip_id": str(clip_id), "video_id": video_id, "privacy": meta[3]})
        return video_id
    except Exception as e:
        await finish(YouTubeUploadStatus.FAILED, error=f"{type(e).__name__}: {e}"[:500])
        raise
    finally:
        if own_client:
            await client.aclose()
        shutil.rmtree(workdir, ignore_errors=True)
