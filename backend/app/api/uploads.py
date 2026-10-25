import asyncio
import logging
import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, Db, Urls
from app.config import get_settings
from app.db.models import Clip, Session, SessionStatus
from app.schemas import SessionOut, UploadCreate, UploadOut
from app.services.serialize import session_out
from app.services.storage import get_storage
from app.worker.enqueue import enqueue_pipeline

router = APIRouter(prefix="/uploads", tags=["uploads"])
log = logging.getLogger(__name__)

_ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".flv", ".ts"}


@router.post("", response_model=UploadOut, status_code=201)
async def create_upload(body: UploadCreate, user: CurrentUser, db: Db) -> UploadOut:
    """Create a session and return a presigned PUT URL. The video goes straight to storage, never through the API."""
    ext = PurePosixPath(body.filename).suffix.lower() or ".mp4"
    if ext not in _ALLOWED_EXT:
        raise HTTPException(422, f"Unsupported file type {ext}")
    max_mb = get_settings().max_upload_mb
    if body.size_bytes and body.size_bytes > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File is {body.size_bytes / 1024**2:.0f} MB; the limit is {max_mb} MB")
    if body.reel_of is not None:
        source = await db.get(Clip, body.reel_of)
        # Credit your own clip, or anyone's published one; never reveal someone's private clip.
        if source is None or (source.user_id != user.id and source.publish_state != "published"):
            raise HTTPException(404, "reel_of: clip not found")
    session_id = uuid.uuid4()
    prefix = f"sessions/{session_id}"
    source_key = f"{prefix}/source{ext}"
    db.add(
        Session(
            id=session_id,
            user_id=user.id,
            game=body.game,
            title=body.title or PurePosixPath(body.filename).stem,
            started_at=body.started_at,
            storage_prefix=prefix,
            source_key=source_key,
            status=SessionStatus.UPLOADING,
            is_reel=body.as_reel or body.reel_of is not None,
            reel_of_clip_id=body.reel_of,
        )
    )
    await db.commit()
    expires = get_settings().presign_put_expires_s
    url = get_storage().presign_put(source_key, body.content_type, expires)
    log.info("upload created", extra={"session_id": str(session_id), "user_id": str(user.id)})
    return UploadOut(
        session_id=session_id,
        upload_url=url,
        headers={"Content-Type": body.content_type},
        expires_in_s=expires,
        storage_key=source_key,
    )


@router.post("/{session_id}/complete", response_model=SessionOut, status_code=202)
async def complete_upload(session_id: uuid.UUID, user: CurrentUser, db: Db, urls: Urls) -> SessionOut:
    """Call after the PUT succeeds. Verifies the object exists, then queues processing."""
    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(404, "Session not found")
    if session.user_id != user.id:
        raise HTTPException(403, "Not your session")
    if session.status != SessionStatus.UPLOADING:
        raise HTTPException(409, f"Session is already {session.status}")
    if not await asyncio.to_thread(get_storage().exists, session.source_key):
        raise HTTPException(400, "Upload not found in storage; PUT the file to upload_url first")
    session.status = SessionStatus.QUEUED
    session.last_step = None
    session.failed_step = None
    session.error = None
    await db.commit()
    await run_in_threadpool(enqueue_pipeline, session.id)
    log.info("upload complete, queued", extra={"session_id": str(session.id)})
    return session_out(session, user, urls)
