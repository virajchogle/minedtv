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
