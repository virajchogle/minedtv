"""reels: sessions can be marked as a reel and credit the clip they were made from

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("is_reel", sa.Boolean, nullable=False, server_default="false"))
    op.add_column("sessions", sa.Column("reel_of_clip_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_sessions_reel_of_clip_id", "sessions", "clips", ["reel_of_clip_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_reel_of_clip_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "reel_of_clip_id")
    op.drop_column("sessions", "is_reel")
