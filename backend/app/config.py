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

    # --- accounts ---
    # Signs login tokens. Required for /auth; generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    auth_secret: str | None = None
    auth_token_ttl_days: int = Field(default=30, ge=1)
    # Accounts with these emails are dev users: they can act as anyone by sending X-User-Id.
    dev_emails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    # false: X-User-Id alone still works (demo clients like the Android app). true: identity comes
    # only from a login token, and X-User-Id is honoured for dev users only.
    require_login: bool = False

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
    gemini_model: str = "gemini-3.5-flash-lite"
    creator_inline_limit_mb: int = Field(default=20, gt=0)
    creator_frame_sample_fps: float = Field(default=0.25, gt=0)
    creator_max_upload_mb: int = Field(default=500, gt=0)
    creator_request_timeout_s: int = Field(default=90, ge=10, le=600)
    creator_persona_count: int = Field(default=9, ge=3, le=15)
    creator_persona_model: str = "gemini-3.1-flash-lite"
    # Direct-upload video virality samples frames locally in parallel with the one
    # Gemini content-analysis call, then blends this much frame evidence into the
    # deterministic persona-cascade score. It never calls Gemini once per frame.
    creator_virality_sample_fps: float = Field(default=0.5, gt=0, le=4)
    creator_virality_max_frames: int = Field(default=240, ge=12, le=2000)
    creator_virality_frame_weight: float = Field(default=0.25, ge=0, le=0.5)
    # Content moderation (app/ml/moderation.py). Same cheap model tier as persona
    # generation; this is a short classification call, not full video analysis.
    moderation_model: str = "gemini-3.1-flash-lite"
    # How many already-extracted frames (see step_frames) to sample evenly across the
    # video and send alongside the transcript, so on-screen text/imagery is judged too.
    # They're already small (frame_thumb_width) and already in storage, so this adds no
    # new extraction work, just a handful of extra bytes on the one classification call.
    moderation_max_frames: int = Field(default=8, ge=0, le=20)
    # Tried in order when the main model is overloaded or rate limited (creator packs for clips).
    gemini_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gemini-3.5-flash"]
    )

    # --- YouTube posting (OAuth web client from Google Cloud console) ---
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    # Must exactly match an "Authorized redirect URI" on the OAuth client. Defaults to
    # {public_api_base_url or request base}/youtube/callback.
    youtube_redirect_uri: str | None = None
    # Fernet key that encrypts stored refresh tokens (and signs the OAuth state).
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    youtube_token_key: str | None = None
    # Where the browser lands after connecting YouTube (e.g. the web app's library page).
    frontend_url: str | None = None

    # --- processing ---
    segment_seconds: int = 2
    transcode_height: int = 720
    transcode_crf: int = 23
    frame_sample_fps: float = 1.0
    frame_thumb_width: int = 320
    transcript_min_window_ms: int = 5000
    transcript_max_window_ms: int = 10000
    auto_clip_count: int = 3
    # On-demand frame virality highlights. This uses the frame embeddings already produced by
    # the pipeline, so it does not re-read or re-upload the video.
    # Run the frame scorer on every processed upload; its clips replace the event-based ones.
    auto_frame_highlights: bool = True
    frame_highlight_count: int = Field(default=3, ge=1, le=10)
    frame_highlight_duration_ms: int = Field(default=30_000, ge=3_000, le=120_000)
    frame_virality_min_score: float = Field(default=0.42, ge=0, le=1)
    standalone_highlight_dir: str = ".data/standalone-highlights"
    standalone_highlight_ttl_s: int = Field(default=86_400, ge=300)
    standalone_highlight_sample_fps: float = Field(default=0.5, gt=0, le=4)
    # Bound extraction work for long direct uploads. At 240 frames a ten-minute
    # recording is sampled at 0.4 fps instead of growing without limit.
    standalone_highlight_max_frames: int = Field(default=240, ge=12, le=2000)
    standalone_mobile_width: int = Field(default=720, ge=360, le=2160, multiple_of=2)
    standalone_mobile_height: int = Field(default=1280, ge=640, le=3840, multiple_of=2)
    stored_highlight_max_minutes: int = Field(default=10, ge=1, le=90)
    stored_highlight_max_source_mb: int = Field(default=1024, ge=1)
    # Public R2 catalog stored beside videos. Jobs fetch only the selected MP3.
    highlight_music_catalog_url: str = "https://pub-415da819582e4b6390d0637419173960.r2.dev/music/catalog.json"
    highlight_music_volume: float = Field(default=0.50, ge=0.0, le=1.0)
    highlight_music_speech_volume: float = Field(default=0.30, ge=0.0, le=1.0)
    # Publish state for clips the pipeline creates. "draft" keeps new uploads private until the owner
    # publishes; "published" puts them straight in the feed (useful until the app has a publish button).
    new_clip_publish_state: Literal["draft", "ready", "published"] = "draft"
    # A clip is a "short" (Reels tab) when it's vertical and at most this long; everything else is "long".
    short_max_duration_s: int = Field(default=60, ge=5, le=600)
    upload_concurrency: int = 8
    # Uploads over these limits are refused (size) or fail at the probe step (length), so one huge
    # file can't run the worker into its job timeout.
    max_upload_mb: int = Field(default=4096, gt=0)
    max_video_minutes: int = Field(default=90, gt=0)

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
    # A viewer's repeat views of the same clip within this window count once.
    view_dedup_minutes: int = Field(default=30, ge=1)

    @field_validator(
        "s3_endpoint_url", "s3_public_endpoint_url", "storage_public_base_url", "public_api_base_url",
        "youtube_client_id", "youtube_client_secret", "youtube_redirect_uri", "youtube_token_key", "frontend_url",
        "auth_secret",
        mode="before",
    )
    @classmethod
    def _empty_is_none(cls, v):
        return v or None

    @field_validator("cors_origins", "api_keys", "gemini_fallback_models", "dev_emails", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("dev_emails")
    @classmethod
    def _lower_emails(cls, v: list[str]) -> list[str]:
        return [e.lower() for e in v]

    @property
    def signing_endpoint_url(self) -> str | None:
        return self.s3_public_endpoint_url or self.s3_endpoint_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
