"""clip publish state: draft / ready / published

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing clips were already visible in the feed, so they start out published.
    op.add_column("clips", sa.Column("publish_state", sa.String(16), nullable=False, server_default="published"))
    op.add_column("clips", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE clips SET published_at = created_at")
    op.alter_column("clips", "publish_state", server_default="draft")
    op.create_check_constraint("ck_clips_publish_state", "clips", "publish_state IN ('draft', 'ready', 'published')")
    op.create_index("ix_clips_state_created", "clips", ["publish_state", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_clips_state_created", table_name="clips")
    op.drop_constraint("ck_clips_publish_state", "clips")
    op.drop_column("clips", "published_at")
    op.drop_column("clips", "publish_state")
