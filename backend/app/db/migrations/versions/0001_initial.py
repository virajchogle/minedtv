"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from app.config import get_settings

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed at migration time. Changing EMBEDDING_DIM later needs a new migration
# (and re-embedding), since pgvector columns have a fixed size.
DIM = get_settings().embedding_dim


def _pk():
    return sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _session_fk():
    return sa.Column("session_id", sa.Uuid, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        _pk(),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("avatar_url", sa.Text),
        _created(),
    )

    op.create_table(
        "sessions",
        _pk(),
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("game", sa.String(128)),
        sa.Column("title", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.BigInteger),
        sa.Column("storage_prefix", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        _created(),
        sa.Column("source_key", sa.Text, nullable=False),
        sa.Column("poster_key", sa.Text),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("fps", sa.Float),
        sa.Column("has_audio", sa.Boolean),
        sa.Column("last_step", sa.String(32)),
        sa.Column("failed_step", sa.String(32)),
        sa.Column("error", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "segments",
        _pk(),
        _session_fk(),
        sa.Column("idx", sa.Integer, nullable=False),
        sa.Column("start_ms", sa.BigInteger, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("storage_key", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        _created(),
    )
    op.create_index("ix_segments_session_idx", "segments", ["session_id", "idx"], unique=True)

    op.create_table(
        "clips",
        _pk(),
        _session_fk(),
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("start_ms", sa.BigInteger, nullable=False),
        sa.Column("end_ms", sa.BigInteger, nullable=False),
        sa.Column("thumbnail_key", sa.Text),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("view_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("like_count", sa.BigInteger, nullable=False, server_default="0"),
        _created(),
        sa.Column("kind", sa.String(16), nullable=False, server_default="user"),
        sa.CheckConstraint("start_ms >= 0 AND end_ms > start_ms", name="ck_clips_range"),
    )
    op.create_index("ix_clips_user_id", "clips", ["user_id"])
    op.create_index("ix_clips_created_id", "clips", ["created_at", "id"])
    op.create_index("ix_clips_session_range", "clips", ["session_id", "start_ms", "end_ms"])

    op.create_table(
        "frames",
        _pk(),
        _session_fk(),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("thumbnail_key", sa.Text),
        sa.Column("embedding", Vector(DIM)),
    )
    op.create_index("ix_frames_session_t", "frames", ["session_id", "t_ms"])
    op.create_index(
        "ix_frames_embedding_hnsw",
        "frames",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "transcripts",
        _pk(),
        _session_fk(),
        sa.Column("start_ms", sa.BigInteger, nullable=False),
        sa.Column("end_ms", sa.BigInteger, nullable=False),
        sa.Column("speaker", sa.String(64)),
        sa.Column("text", sa.Text, nullable=False),
        # Generated column keeps text_tsv in sync with text.
        sa.Column("text_tsv", TSVECTOR, sa.Computed("to_tsvector('english', coalesce(text, ''))", persisted=True)),
        sa.Column("embedding", Vector(DIM)),
    )
    op.create_index("ix_transcripts_session_start", "transcripts", ["session_id", "start_ms"])
    op.create_index("ix_transcripts_text_tsv", "transcripts", ["text_tsv"], postgresql_using="gin")
    op.create_index(
        "ix_transcripts_embedding_hnsw",
        "transcripts",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "events",
        _pk(),
        _session_fk(),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("source", sa.String(64)),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
    )
    op.create_index("ix_events_session_t", "events", ["session_id", "t_ms"])
    op.create_index("ix_events_type_score", "events", ["type", "score"])

    op.create_table(
        "likes",
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("clip_id", sa.Uuid, sa.ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True),
        _created(),
    )
    op.create_index("ix_likes_clip_id", "likes", ["clip_id"])


def downgrade() -> None:
    for table in ("likes", "events", "transcripts", "frames", "clips", "segments", "sessions", "users"):
        op.drop_table(table)
