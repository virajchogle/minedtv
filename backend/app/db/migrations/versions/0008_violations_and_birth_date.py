"""itemized moderation violations (category + timestamp) and user birth_date

Backfills every existing user to an adult birth_date so nothing that already
published is retroactively hidden, except the account named "jannu" (any
case), which is set to 16 so age-gating has a real account to demonstrate
against.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("moderation_violations", JSONB, nullable=False, server_default="[]"))
    op.add_column("clips", sa.Column("moderation_violations", JSONB, nullable=False, server_default="[]"))
    op.add_column("users", sa.Column("birth_date", sa.Date))

    # Everyone existing becomes a clean 25-year-old adult...
    op.execute("UPDATE users SET birth_date = (CURRENT_DATE - INTERVAL '25 years') WHERE birth_date IS NULL")
    # ...except jannu, who is 16 so under-18 gating has a real account to test.
    op.execute(
        "UPDATE users SET birth_date = (CURRENT_DATE - INTERVAL '16 years') WHERE lower(username) = 'jannu'"
    )


def downgrade() -> None:
    op.drop_column("users", "birth_date")
    op.drop_column("clips", "moderation_violations")
    op.drop_column("sessions", "moderation_violations")
