"""password accounts and dev users

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(254)))
    op.add_column("users", sa.Column("password_hash", sa.Text))
    op.add_column("users", sa.Column("is_dev", sa.Boolean, nullable=False, server_default="false"))
    op.create_unique_constraint("uq_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_column("users", "is_dev")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
