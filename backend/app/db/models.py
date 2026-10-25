import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

EMBEDDING_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    pass


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SessionStatus:
    UPLOADING = "uploading"
    QUEUED = "queued"
    PROBING = "probing"
    SEGMENTING = "segmenting"
    THUMBNAILS = "thumbnails"
    FRAMES = "frames"
    AUDIO = "audio"
    MODERATING = "moderating"
    HIGHLIGHTS = "highlights"
    FINALIZING = "finalizing"
    READY = "ready"
    FAILED = "failed"
    # Terminal: transcript moderation found severe content. No clip is ever
    # created for this session — distinct from FAILED, which is a technical error.
    BLOCKED = "blocked"


PUBLISH_STATES = ("draft", "ready", "published")
UNPUBLISHED_STATES = ("draft", "ready")
MODERATION_SEVERITIES = ("none", "mild", "severe")

# Pipeline steps in order, and the session status shown while each one runs.
PIPELINE_STEPS = ["probe", "segment", "thumbnails", "frames", "audio", "moderate", "highlights", "finalize"]
STEP_STATUS = {
    "probe": SessionStatus.PROBING,
    "segment": SessionStatus.SEGMENTING,
    "thumbnails": SessionStatus.THUMBNAILS,
    "frames": SessionStatus.FRAMES,
    "audio": SessionStatus.AUDIO,
    "moderate": SessionStatus.MODERATING,
    "highlights": SessionStatus.HIGHLIGHTS,
    "finalize": SessionStatus.FINALIZING,
}


def is_adult(birth_date: date | None, min_age: int = 18) -> bool:
    """No birth_date (anonymous viewer, or a pre-this-column row never backfilled) is
    treated as NOT an adult — the safe default for gating age-restricted content."""
    if birth_date is None:
        return False
    today = date.today()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
    return age >= min_age


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    # Set for accounts that sign up with a password; demo users made via POST /users have neither.
    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    # Dev accounts (emails in DEV_EMAILS) may act as any user via X-User-Id.
    is_dev: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Required at signup going forward; nullable so it doesn't break rows that predate this
    # column. A user with no birth_date is treated as NOT an adult (safe default); see is_adult().
    birth_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()

    @property
    def is_adult(self) -> bool:
        return is_adult(self.birth_date)


class Session(Base):
    """One uploaded recording."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("moderation_severity IN ('none', 'mild', 'severe')", name="ck_sessions_moderation_severity"),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    game: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    storage_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SessionStatus.UPLOADING)
    created_at: Mapped[datetime] = _created()

    # Processing bookkeeping beyond the core spec columns.
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    poster_key: Mapped[str | None] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)
    last_step: Mapped[str | None] = mapped_column(String(32))  # last pipeline step that completed
    failed_step: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Transcript + frame moderation (see app/ml/moderation.py). "severe" never
    # reaches this row as READY — the pipeline stops and leaves status=BLOCKED instead.
    moderation_severity: Mapped[str] = mapped_column(String(16), nullable=False, default="none", server_default="none")
    moderation_reason: Mapped[str | None] = mapped_column(Text)
    age_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # [{category, timestamp_ms, note}, ...], itemized findings with where they occur.
    moderation_violations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")


class Segment(Base):
    """A 2-second HLS segment of a session."""

    __tablename__ = "segments"
    __table_args__ = (Index("ix_segments_session_idx", "session_id", "idx", unique=True),)

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = _created()


class Clip(Base):
    """A time range over its session's segments ("clips as views")."""

    __tablename__ = "clips"
    __table_args__ = (
        Index("ix_clips_created_id", "created_at", "id"),
        Index("ix_clips_session_range", "session_id", "start_ms", "end_ms"),
        Index("ix_clips_state_created", "publish_state", "created_at", "id"),
        CheckConstraint("publish_state IN ('draft', 'ready', 'published')", name="ck_clips_publish_state"),
        CheckConstraint("start_ms >= 0 AND end_ms > start_ms", name="ck_clips_range"),
    )

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    view_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    like_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()
    # "auto" clips are (re)created by the pipeline's finalize step; "user" clips are never touched by it.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="user", server_default="user")
    # draft -> ready (queued to post to YouTube) -> published (visible in feed/search). Unpublished
    # clips are owner-only; virality simulation only runs on them.
    publish_state: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Copied from the owning session's moderation verdict when this clip is created.
    age_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    moderation_violations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")


class Frame(Base):
    __tablename__ = "frames"
    __table_args__ = (
        Index("ix_frames_session_t", "session_id", "t_ms"),
        Index(
            "ix_frames_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    t_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    thumbnail_key: Mapped[str | None] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM))


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        Index("ix_transcripts_session_start", "session_id", "start_ms"),
        Index("ix_transcripts_text_tsv", "text_tsv", postgresql_using="gin"),
        Index(
            "ix_transcripts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', coalesce(text, ''))", persisted=True))
    embedding = mapped_column(Vector(EMBEDDING_DIM))


class Event(Base):
    """Highlight events written by the highlight detector."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_session_t", "session_id", "t_ms"),
        Index("ix_events_type_score", "type", "score"),
    )

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    t_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict, server_default="{}")


class Like(Base):
    __tablename__ = "likes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True, index=True)
    created_at: Mapped[datetime] = _created()


class ClipDailyViews(Base):
    """Views per clip per UTC day, for analytics. Flushed from Redis with the view counters."""

    __tablename__ = "clip_daily_views"

    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Comment(Base):
    """A comment on a clip. parent_id makes it a reply (one level of threading)."""

    __tablename__ = "comments"
    __table_args__ = (
        Index("ix_comments_clip_created", "clip_id", "created_at"),
        Index("ix_comments_parent", "parent_id"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 1000", name="ck_comments_body_length"),
    )

    id: Mapped[uuid.UUID] = _pk()
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (
        Index("ix_follows_followee", "followee_id", "created_at"),
        CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
    )

    follower_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    followee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = _created()


class NotificationType:
    LIKE = "like"  # someone liked your clip
    COMMENT = "comment"  # someone commented on your clip
    REPLY = "reply"  # someone replied to your comment
    FOLLOW = "follow"  # someone followed you
    UPLOAD_READY = "upload_ready"  # your upload finished processing
    VIRALITY_READY = "virality_ready"  # your virality check finished
    YOUTUBE_POSTED = "youtube_posted"  # your clip is on YouTube (or the post failed)

    ALL = (LIKE, COMMENT, REPLY, FOLLOW, UPLOAD_READY, VIRALITY_READY, YOUTUBE_POSTED)


class Notification(Base):
    """Something that happened that a user should hear about. Written by the action itself."""

    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_created", "user_id", "created_at"),
        Index("ix_notifications_unread", "user_id", postgresql_where="read_at IS NULL"),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    clip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"))
    comment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("comments.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class YouTubeAccount(Base):
    """A user's connected YouTube channel. The refresh token is stored encrypted."""

    __tablename__ = "youtube_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(64), nullable=False)
    channel_title: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class YouTubeUploadStatus:
    QUEUED = "queued"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"


class YouTubeUpload(Base):
    """One attempt to post a clip to YouTube."""

    __tablename__ = "youtube_uploads"
    __table_args__ = (Index("ix_youtube_uploads_clip_created", "clip_id", "created_at"),)

    id: Mapped[uuid.UUID] = _pk()
    clip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clips.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=YouTubeUploadStatus.QUEUED)
    privacy: Mapped[str] = mapped_column(String(16), nullable=False, default="private")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    video_id: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
