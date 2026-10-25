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
        title="MinedIt API",
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

    from app.api import accounts, analytics, clips, creator, feed, notifications, search, sessions, social, uploads, users, youtube

    for module in (accounts, uploads, sessions, clips, feed, search, users, analytics, social, notifications, creator, youtube):
        app.include_router(module.router)

    @app.post("/warmup", tags=["health"])
    async def warmup() -> dict:
        """Wake the GPU embedder so the first real search isn't a cold start. Call it on app
        launch without awaiting the result: it returns once the model is warm (up to ~60 s cold)."""
        from app.ml.registry import get_embedder

        t0 = asyncio.get_running_loop().time()
        try:
            await asyncio.wait_for(asyncio.to_thread(get_embedder().embed_texts, ["warm up"]), timeout=120)
            status = "warm"
        except Exception:  # noqa: BLE001 - best effort
            log.warning("warmup failed", exc_info=True)
            status = "failed"
        return {"status": status, "ms": round((asyncio.get_running_loop().time() - t0) * 1000)}

    @app.get("/config", tags=["health"])
    async def config() -> dict:
        """Read-only view of the models and search settings this server runs with (no secrets)."""
        st = get_settings()
        return {
            "models": {
                "embedder": st.embedder_backend,
                "transcriber": st.transcriber_backend,
                "highlights": st.highlight_backend,
                "creator": st.gemini_model if st.gemini_api_key else None,
                "creator_fallbacks": st.gemini_fallback_models if st.gemini_api_key else [],
                "personas": st.creator_persona_model if st.gemini_api_key else None,
            },
            "search": {
                "rrf_k": st.rrf_k,
                "visual_min_score": st.visual_min_score,
                "visual_full_score": st.visual_full_score,
                "visual_relative_cutoff": st.visual_relative_cutoff,
                "speech_min_score": st.speech_min_score,
                "speech_full_score": st.speech_full_score,
                "speech_only_min_score": st.speech_only_min_score,
                "image_min_sim": st.image_min_sim,
                "image_full_sim": st.image_full_sim,
            },
            "features": {
                "gemini": bool(st.gemini_api_key),
                "youtube": bool(st.youtube_client_id and st.youtube_client_secret and st.youtube_token_key),
                "accounts": bool(st.auth_secret),
                "require_login": st.require_login,
            },
            "limits": {
                "max_upload_mb": st.max_upload_mb,
                "max_video_minutes": st.max_video_minutes,
                "creator_max_upload_mb": st.creator_max_upload_mb,
                "highlight_max_minutes": st.stored_highlight_max_minutes,
                "highlight_max_source_mb": st.stored_highlight_max_source_mb,
                "highlight_max_sampled_frames": st.standalone_highlight_max_frames,
                "short_max_duration_s": st.short_max_duration_s,
            },
        }

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
