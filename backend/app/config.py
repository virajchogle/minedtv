"""All runtime configuration. Every value comes from env vars (or .env); see .env.example."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app ---
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = True
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])
    # Shared API keys (comma-separated). When set, requests need X-API-Key: <one of them>.
    # Empty = no check (local dev). Several keys allow rotation without downtime.
    api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # Absolute base URL used in links the API returns (playlist URLs). Defaults to the request's own base URL.
    public_api_base_url: str | None = None

    # --- database ---
    database_url: str = "postgresql+asyncpg://minedtv:minedtv@localhost:5432/minedtv"
    # Supabase's pooler (port 6543) runs pgbouncer in transaction mode, which breaks
    # asyncpg's prepared statement cache. Set true when pointing at the pooler.
    db_pgbouncer: bool = False
    db_pool_size: int = 5

    # --- redis / queue ---
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "pipeline"
    job_timeout_s: int = 3600

    # --- object storage ---
    storage_backend: Literal["s3", "local"] = "s3"
    s3_endpoint_url: str | None = "http://localhost:8333"
    # Endpoint used when signing URLs handed to clients. Differs from s3_endpoint_url
    # when the API reaches storage over an internal hostname (e.g. http://s3:8333 in compose).
    s3_public_endpoint_url: str | None = None
    s3_region: str = "auto"
    s3_access_key_id: str = "local"
    s3_secret_access_key: str = "localsecret"
    s3_bucket: str = "minedtv"
    # If set (e.g. an R2 public bucket URL or CDN), playback/thumbnail URLs are
    # {public_base_url}/{key} instead of presigned GETs.
    storage_public_base_url: str | None = None
    presign_get_expires_s: int = 3600
    presign_put_expires_s: int = 3600
    local_storage_dir: str = ".data/storage"

    # --- ml ---
    embedding_dim: int = 768
    # "stub", "modal", or an import path "package.module:ClassName"
    embedder_backend: str = "stub"
    transcriber_backend: str = "stub"
    highlight_backend: str = "stub"
    modal_app_name: str = "minedtv-ml"
    embed_batch_size: int = 32

    # Gemini-powered creator metadata. Leave the key empty to disable /creator/analyze.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    creator_inline_limit_mb: int = Field(default=20, gt=0)
    creator_frame_sample_fps: float = Field(default=0.25, gt=0)
    creator_max_upload_mb: int = Field(default=500, gt=0)
    # Tried in order when the main model is overloaded or rate limited (creator packs for clips).
    gemini_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gemini-3.5-flash", "gemini-flash-latest"]
    )

    # --- processing ---
    segment_seconds: int = 2
    transcode_height: int = 720
    transcode_crf: int = 23
    frame_sample_fps: float = 1.0
    frame_thumb_width: int = 320
    transcript_min_window_ms: int = 5000
    transcript_max_window_ms: int = 10000
    auto_clip_count: int = 3
    upload_concurrency: int = 8

    # --- search ---
    search_cache_ttl_s: int = 300
    rrf_k: int = 60
    search_signal_limit: int = 40
    clip_window_ms: int = 15000
    moment_window_ms: int = 5000
    # Semantic-hit cutoffs (CLIP ViT-L/14 scale, measured on real gameplay; re-measure if the model changes).
    # Visual text search is contrastive: sim(templated query) - sim(generic gameplay baseline).
    visual_min_score: float = 0.035
    visual_full_score: float = 0.10
    visual_relative_cutoff: float = 0.75  # drop frames below this fraction of the best visual score
    # Speech is contrastive too: sim(query) - sim(generic talking baseline); lines < 3 words are skipped.
    speech_min_score: float = 0.03
    speech_full_score: float = 0.12
    speech_only_min_score: float = 0.06  # stronger bar when speech is a moment's only signal
    image_min_sim: float = 0.55
    image_full_sim: float = 0.85

    # --- counters ---
    counter_flush_interval_s: int = 30

    @field_validator("s3_endpoint_url", "s3_public_endpoint_url", "storage_public_base_url", "public_api_base_url", mode="before")
    @classmethod
    def _empty_is_none(cls, v):
        return v or None

    @field_validator("cors_origins", "api_keys", "gemini_fallback_models", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def signing_endpoint_url(self) -> str | None:
        return self.s3_public_endpoint_url or self.s3_endpoint_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
