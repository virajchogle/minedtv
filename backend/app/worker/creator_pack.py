"""Creator pack (titles, captions, hashtags, YouTube metadata) for a clip that's already uploaded.

Renders the clip's MP4 (reusing the export), runs it through the Gemini creator engine,
and stores the JSON next to the export. Like exports, packs are keyed by the clip's
range, so trimming a clip produces a fresh pack. If the configured Gemini model is
overloaded, the job falls back to the next model in GEMINI_FALLBACK_MODELS.
"""

import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.db.models import Clip
from app.schemas import CreatorPackOut
from app.worker.export import STATUS_TTL_S, export_clip
from app.worker.pipeline import Deps

log = logging.getLogger("creator_pack")


def pack_key(clip_id: uuid.UUID | str, start_ms: int, end_ms: int) -> str:
    return f"creator/{clip_id}/{start_ms}-{end_ms}.json"


def pack_status_key(clip_id: uuid.UUID | str, start_ms: int, end_ms: int) -> str:
    return f"creator:{clip_id}:{start_ms}-{end_ms}"


def is_capacity_error(exc: BaseException) -> bool:
    """Overloaded or rate-limited model: worth retrying on a different model."""
    chain, seen = [], exc
    while seen is not None and len(chain) < 5:
        chain.append(seen)
        seen = seen.__cause__ or seen.__context__
    text = " ".join(f"{type(e).__name__} {e}" for e in chain).lower()
    return any(s in text for s in ("503", "429", "high demand", "unavailable", "resource_exhausted", "overloaded", "rate limit"))


def analyze_with_fallback(
    video_path: Path, settings: Settings, engine_factory: Callable[[Settings], object] | None = None
) -> tuple[CreatorPackOut, str]:
    """Run the creator engine, trying fallback models on capacity errors. Returns (pack, model used)."""
    if engine_factory is None:
        from app.ml.gemini_creator import GeminiCreatorEngine

        engine_factory = GeminiCreatorEngine
    models = [settings.gemini_model, *[m for m in settings.gemini_fallback_models if m != settings.gemini_model]]
    last: BaseException | None = None
    for model in models:
        engine = engine_factory(settings.model_copy(update={"gemini_model": model}))
        try:
            return engine.analyze(video_path, "video/mp4"), model
        except Exception as e:
            if not is_capacity_error(e):
                raise
            log.warning("gemini model busy, trying next", extra={"model": model})
            last = e
    raise RuntimeError(f"all Gemini models busy ({', '.join(models)})") from last


async def build_creator_pack(
    clip_id: uuid.UUID | str, deps: Deps, redis=None, engine_factory: Callable[[Settings], object] | None = None
) -> str:
    """Create (or reuse) the clip's creator pack. Returns its storage key."""
    clip_id = uuid.UUID(str(clip_id))
    async with deps.sessionmaker() as db:
        clip = await db.get(Clip, clip_id)
        if clip is None:
            raise LookupError(f"clip {clip_id} not found")
        start, end = clip.start_ms, clip.end_ms
    key, skey = pack_key(clip_id, start, end), pack_status_key(clip_id, start, end)

    async def set_status(value: str):
        if redis is not None:
            await redis.set(skey, value, ex=STATUS_TTL_S)

    if await asyncio.to_thread(deps.storage.exists, key):
        await set_status("ready")
        return key

    await set_status("processing")
    workdir = Path(tempfile.mkdtemp(prefix=f"minedtv-creator-{clip_id}-"))
    try:
        mp4_key = await export_clip(clip_id, deps, redis)
        mp4 = workdir / "clip.mp4"
        await asyncio.to_thread(deps.storage.download_file, mp4_key, mp4)
        pack, model = await asyncio.to_thread(analyze_with_fallback, mp4, deps.settings, engine_factory)
        body = {"model": model, "pack": pack.model_dump(mode="json")}
        await asyncio.to_thread(deps.storage.put_bytes, key, json.dumps(body).encode(), "application/json")
        await set_status("ready")
        log.info("creator pack ready", extra={"clip_id": str(clip_id), "model": model})
        return key
    except Exception as e:
        await set_status(f"failed:{type(e).__name__}: {e}"[:500])
        raise
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
