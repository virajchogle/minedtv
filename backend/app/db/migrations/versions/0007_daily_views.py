"""daily views per clip, for analytics

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clip_daily_views",
        sa.Column("clip_id", sa.Uuid, sa.ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("views", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_clip_daily_views_day", "clip_daily_views", ["day"])


def downgrade() -> None:
    op.drop_index("ix_clip_daily_views_day", "clip_daily_views")
    op.drop_table("clip_daily_views")
