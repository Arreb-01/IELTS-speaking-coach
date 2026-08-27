"""learning path: users.placement_at, sessions.question_ids, daily_tasks

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json() -> sa.types.TypeEngine:
    from app.db.models import JSONVariant

    return JSONVariant


def upgrade() -> None:
    op.add_column("users", sa.Column("placement_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("practice_sessions", sa.Column("question_ids", _json(), nullable=True))

    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan_date", sa.Date(), nullable=False),
        # topic / special / corpus
        sa.Column("task_type", sa.String(20), nullable=False),
        sa.Column("dimension", sa.String(20), nullable=True),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("part", sa.SmallInteger(), nullable=True),
        sa.Column("title_zh", sa.String(100), nullable=False),
        sa.Column("desc_zh", sa.String(200), nullable=False),
        sa.Column("payload", _json(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("sort", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_tasks_user_date", "daily_tasks", ["user_id", "plan_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_tasks_user_date", table_name="daily_tasks")
    op.drop_table("daily_tasks")
    op.drop_column("practice_sessions", "question_ids")
    op.drop_column("users", "placement_at")
