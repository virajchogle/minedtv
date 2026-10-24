"""MP4 export of a clip (for sharing to TikTok / Reels, which need a file, not HLS).

The export is keyed by the clip's current range, so a finished export is reused until the
clip is trimmed or extended. Status lives in Redis while the job runs; the MP4's existence
in storage is the source of truth once it's done.
"""

import asyncio
import logging
import shutil
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.models import Clip, Segment
from app.services.playlist import segments_in_range
from app.worker import media
from app.worker.pipeline import Deps, _upload_many

log = logging.getLogger("export")

STATUS_TTL_S = 6 * 3600


def export_key(clip_id: uuid.UUID | str, start_ms: int, end_ms: int) -> str:
    return f"exports/{clip_id}/{start_ms}-{end_ms}.mp4"


def status_key(clip_id: uuid.UUID | str, start_ms: int, end_ms: int) -> str:
    return f"export:{clip_id}:{start_ms}-{end_ms}"


def render_mp4(segment_paths: list[Path], offset_ms: int, duration_ms: int, out: Path) -> Path:
    """Join HLS segments and cut [offset, offset+duration) frame-accurately into a web-ready MP4."""
    listing = out.parent / "concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in segment_paths))
    media._run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(listing),
        "-ss", f"{offset_ms / 1000:.3f}", "-t", f"{duration_ms / 1000:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(out),
    ])
    return out


async def export_clip(clip_id: uuid.UUID | str, deps: Deps, redis=None) -> str:
    """Render and upload the clip's MP4. Returns the storage key."""
    clip_id = uuid.UUID(str(clip_id))
    async with deps.sessionmaker() as db:
        clip = await db.get(Clip, clip_id)
        if clip is None:
            raise LookupError(f"clip {clip_id} not found")
        start, end, session_id = clip.start_ms, clip.end_ms, clip.session_id
        segments = (await db.scalars(select(Segment).where(Segment.session_id == session_id).order_by(Segment.idx))).all()
    key, skey = export_key(clip_id, start, end), status_key(clip_id, start, end)

    async def set_status(value: str):
        if redis is not None:
            await redis.set(skey, value, ex=STATUS_TTL_S)

    if await asyncio.to_thread(deps.storage.exists, key):
        await set_status("ready")
        return key

    chosen = segments_in_range(segments, start, end)
    if not chosen:
        await set_status("failed:no segments cover the clip")
        raise ValueError("no segments cover the clip")
    await set_status("processing")
    workdir = Path(tempfile.mkdtemp(prefix=f"minedtv-export-{clip_id}-"))
    try:
        paths = [workdir / f"{s.idx:05d}.ts" for s in chosen]
        await asyncio.to_thread(
            lambda: [deps.storage.download_file(s.storage_key, p) for s, p in zip(chosen, paths, strict=True)]
        )
        out = await asyncio.to_thread(render_mp4, paths, start - chosen[0].start_ms, end - start, workdir / "clip.mp4")
        await asyncio.to_thread(_upload_many, deps.storage, [(key, out, "video/mp4")], 1)
        await set_status("ready")
        log.info("exported clip", extra={"clip_id": str(clip_id), "bytes": out.stat().st_size, "key": key})
        return key
    except Exception as e:
        await set_status(f"failed:{type(e).__name__}: {e}"[:500])
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
