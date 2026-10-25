"""transcript content moderation: severity, reason, age-restricted flag

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("moderation_severity", sa.String(16), nullable=False, server_default="none"))
    op.add_column("sessions", sa.Column("moderation_reason", sa.Text))
    op.add_column("sessions", sa.Column("age_restricted", sa.Boolean, nullable=False, server_default="false"))
    op.create_check_constraint(
        "ck_sessions_moderation_severity", "sessions", "moderation_severity IN ('none', 'mild', 'severe')"
    )
    op.add_column("clips", sa.Column("age_restricted", sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("clips", "age_restricted")
    op.drop_constraint("ck_sessions_moderation_severity", "sessions")
    op.drop_column("sessions", "age_restricted")
    op.drop_column("sessions", "moderation_reason")
    op.drop_column("sessions", "moderation_severity")
