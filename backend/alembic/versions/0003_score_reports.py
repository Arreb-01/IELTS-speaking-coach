"""score_reports and turn_analyses

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json() -> sa.types.TypeEngine:
    from app.db.models import JSONVariant

    return JSONVariant


def upgrade() -> None:
    json_type = _json()
    op.create_table(
        "score_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Enum("pending", "processing", "completed", "failed", name="report_status", native_enum=False, length=20), nullable=False),
        sa.Column("overall_band", sa.Numeric(2, 1), nullable=True),
        sa.Column("fluency", sa.Numeric(2, 1), nullable=True),
        sa.Column("lexical", sa.Numeric(2, 1), nullable=True),
        sa.Column("grammar", sa.Numeric(2, 1), nullable=True),
        sa.Column("pronunciation", sa.Numeric(2, 1), nullable=True),
        sa.Column("fluency_metrics", json_type, nullable=True),
        sa.Column("overall_comment_zh", sa.Text(), nullable=True),
        sa.Column("strengths", json_type, nullable=True),
        sa.Column("improvements", json_type, nullable=True),
        sa.Column("expression_upgrades", json_type, nullable=True),
        sa.Column("low_confidence", json_type, nullable=True),
        sa.Column("model_versions", json_type, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["practice_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_score_reports_session_id"),
    )
    op.create_index("ix_score_reports_user_id", "score_reports", ["user_id"])

    op.create_table(
        "turn_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("sentences", json_type, nullable=True),
        sa.Column("pronunciation_detail", json_type, nullable=True),
        sa.Column("filler_hits", json_type, nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["score_reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_turn_analyses_report_id", "turn_analyses", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_turn_analyses_report_id", table_name="turn_analyses")
    op.drop_table("turn_analyses")
    op.drop_index("ix_score_reports_user_id", table_name="score_reports")
    op.drop_table("score_reports")
