"""youtube accounts and uploads

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts(name: str):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "youtube_accounts",
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("channel_id", sa.String(64), nullable=False),
        sa.Column("channel_title", sa.Text),
        sa.Column("refresh_token_enc", sa.Text, nullable=False),
        sa.Column("scopes", sa.Text, nullable=False, server_default=""),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "youtube_uploads",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("clip_id", sa.Uuid, sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("privacy", sa.String(16), nullable=False, server_default="private"),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("tags", JSONB, nullable=False, server_default="[]"),
        sa.Column("video_id", sa.String(32)),
        sa.Column("error", sa.Text),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("status IN ('queued', 'uploading', 'published', 'failed')", name="ck_youtube_uploads_status"),
        sa.CheckConstraint("privacy IN ('private', 'unlisted', 'public')", name="ck_youtube_uploads_privacy"),
    )
    op.create_index("ix_youtube_uploads_clip_created", "youtube_uploads", ["clip_id", "created_at"])
    op.create_index("ix_youtube_uploads_user_id", "youtube_uploads", ["user_id"])


def downgrade() -> None:
    op.drop_table("youtube_uploads")
    op.drop_table("youtube_accounts")
