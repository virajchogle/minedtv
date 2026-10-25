"""frame virality scores and highlight run state

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clips", sa.Column("generation_source", sa.String(32)))
    op.add_column("frames", sa.Column("visibility_score", sa.Float))
    op.execute("UPDATE clips SET generation_source = 'pipeline' WHERE kind = 'auto'")
    op.create_table(
        "frame_highlight_runs",
        sa.Column("session_id", sa.Uuid, sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_count", sa.Integer, nullable=False),
        sa.Column("clip_duration_ms", sa.Integer, nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "frame_virality_scores",
        sa.Column("id", sa.Uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", sa.Uuid, sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frame_id", sa.Uuid, sa.ForeignKey("frames.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("t_ms", sa.BigInteger, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("visual_score", sa.Float, nullable=False),
        sa.Column("novelty_score", sa.Float, nullable=False),
        sa.Column("event_score", sa.Float, nullable=False),
        sa.Column("speech_score", sa.Float, nullable=False),
        sa.Column("visibility_score", sa.Float, nullable=False),
        sa.Column("scene_score", sa.Float, nullable=False),
        sa.Column("selected", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "score BETWEEN 0 AND 1 AND visual_score BETWEEN 0 AND 1 "
            "AND novelty_score BETWEEN 0 AND 1 AND event_score BETWEEN 0 AND 1 "
            "AND speech_score BETWEEN 0 AND 1 AND visibility_score BETWEEN 0 AND 1 "
            "AND scene_score BETWEEN 0 AND 1",
            name="ck_frame_virality_scores_range",
        ),
    )
    op.create_index("ix_frame_virality_session_t", "frame_virality_scores", ["session_id", "t_ms"])
    op.create_index(
        "ix_frame_virality_session_selected",
        "frame_virality_scores",
        ["session_id", "selected", "score"],
    )


def downgrade() -> None:
    op.drop_table("frame_virality_scores")
    op.drop_table("frame_highlight_runs")
    op.drop_column("frames", "visibility_score")
    op.drop_column("clips", "generation_source")
