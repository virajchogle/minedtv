import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.auth import ApiKeyMiddleware
from app.config import Settings, get_settings
from app.db.session import get_engine
from app.log import setup_logging
from app.schemas import HealthOut
from app.services.redis import get_redis
from app.services.storage import get_storage

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    from app.services.counters import flush_loop

    flusher = asyncio.create_task(flush_loop(settings.counter_flush_interval_s))
    log.info("api started", extra={"env": settings.app_env})
    yield
    flusher.cancel()
    await get_engine().dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="MinedTV API",
        version="0.1.0",
        description="Gaming clips with semantic search. Clips are time ranges over stored sessions.",
        lifespan=lifespan,
    )
    # Added before CORS so CORS wraps it: 401s still carry CORS headers the browser can read.
    app.add_middleware(ApiKeyMiddleware, keys=settings.api_keys)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials="*" not in settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api import clips, feed, search, sessions, uploads, users

    for module in (uploads, sessions, clips, feed, search, users):
        app.include_router(module.router)

    @app.get("/health", response_model=HealthOut, tags=["health"])
    async def health() -> HealthOut:
        checks: dict[str, str] = {}

        async def check(name, coro):
            try:
                await asyncio.wait_for(coro, timeout=3)
                checks[name] = "ok"
            except Exception as e:  # noqa: BLE001 - report any failure
                checks[name] = f"error: {type(e).__name__}: {e}"[:200]

        async def db():
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))

        await asyncio.gather(
            check("database", db()),
            check("redis", get_redis().ping()),
            check("storage", asyncio.to_thread(get_storage().ping)),
        )
        return HealthOut(status="ok" if all(v == "ok" for v in checks.values()) else "degraded", checks=checks)

    return app


app = create_app()
