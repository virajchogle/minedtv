"""RQ entry points. RQ calls these synchronously in the worker process."""

import asyncio

from app.config import get_settings
from app.log import setup_logging


def process_session(session_id: str, resume: bool = False) -> str:
    from app.db.session import get_engine
    from app.worker.pipeline import run_pipeline

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    async def main() -> str:
        try:
            return await run_pipeline(session_id, resume=resume)
        finally:
            # Each job gets a fresh event loop, so pooled connections can't be reused across jobs.
            await get_engine().dispose()

    return asyncio.run(main())


def export_clip(clip_id: str) -> str:
    from app.db.session import get_engine
    from app.services.redis import get_redis
    from app.worker.export import export_clip as run_export
    from app.worker.pipeline import Deps

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    async def main() -> str:
        try:
            return await run_export(clip_id, Deps.default(), get_redis())
        finally:
            await get_engine().dispose()
            await get_redis().aclose()

    return asyncio.run(main())


def creator_pack(clip_id: str) -> str:
    from app.db.session import get_engine
    from app.services.redis import get_redis
    from app.worker.creator_pack import build_creator_pack
    from app.worker.pipeline import Deps

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    async def main() -> str:
        try:
            return await build_creator_pack(clip_id, Deps.default(), get_redis())
        finally:
            await get_engine().dispose()
            await get_redis().aclose()

    return asyncio.run(main())


def frame_highlights(session_id: str, requested_count: int, clip_duration_ms: int, make_clips: bool = True) -> str:
    from app.db.session import get_engine
    from app.worker.frame_highlights import run_frame_highlights
    from app.worker.pipeline import Deps

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    async def main() -> str:
        try:
            return await run_frame_highlights(session_id, Deps.default(), requested_count, clip_duration_ms, make_clips)
        finally:
            await get_engine().dispose()

    return asyncio.run(main())


def clip_highlights(clip_id: str, options: dict) -> str:
    from app.db.session import get_engine
    from app.services.redis import get_redis
    from app.worker.clip_highlights import run_clip_highlights
    from app.worker.pipeline import Deps

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    async def main() -> str:
        try:
            return await run_clip_highlights(clip_id, Deps.default(), options, get_redis())
        finally:
            await get_engine().dispose()
            await get_redis().aclose()

    return asyncio.run(main())


def youtube_post(upload_id: str) -> str:
    from app.db.session import get_engine
    from app.services.redis import get_redis
    from app.worker.pipeline import Deps
    from app.worker.youtube_post import post_to_youtube

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)

    async def main() -> str:
        try:
            return await post_to_youtube(upload_id, Deps.default(), get_redis())
        finally:
            await get_engine().dispose()
            await get_redis().aclose()

    return asyncio.run(main())
