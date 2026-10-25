"""youtube posts can upload a rendered montage instead of the plain clip

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("youtube_uploads", sa.Column("kind", sa.String(16), nullable=False, server_default="clip"))
    op.add_column("youtube_uploads", sa.Column("source_key", sa.Text))


def downgrade() -> None:
    op.drop_column("youtube_uploads", "source_key")
    op.drop_column("youtube_uploads", "kind")
