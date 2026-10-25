"""comments, follows and notifications

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _fk(name: str, table: str, nullable: bool = False):
    return sa.Column(name, sa.Uuid, sa.ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _fk("clip_id", "clips"),
        _fk("user_id", "users"),
        _fk("parent_id", "comments", nullable=True),
        sa.Column("body", sa.Text, nullable=False),
        _created(),
        sa.CheckConstraint("char_length(body) BETWEEN 1 AND 1000", name="ck_comments_body_length"),
    )
    op.create_index("ix_comments_clip_created", "comments", ["clip_id", "created_at"])
    op.create_index("ix_comments_parent", "comments", ["parent_id"])
    op.create_index("ix_comments_user_id", "comments", ["user_id"])

    op.create_table(
        "follows",
        sa.Column("follower_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("followee_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        _created(),
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follows_not_self"),
    )
    op.create_index("ix_follows_followee", "follows", ["followee_id", "created_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _fk("user_id", "users"),
        _fk("actor_id", "users", nullable=True),
        sa.Column("type", sa.String(32), nullable=False),
        _fk("clip_id", "clips", nullable=True),
        _fk("comment_id", "comments", nullable=True),
        _fk("session_id", "sessions", nullable=True),
        sa.Column("data", JSONB, nullable=False, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        _created(),
    )
    op.create_index("ix_notifications_user_created", "notifications", ["user_id", "created_at"])
    op.create_index("ix_notifications_unread", "notifications", ["user_id"], postgresql_where=sa.text("read_at IS NULL"))


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("follows")
    op.drop_table("comments")
