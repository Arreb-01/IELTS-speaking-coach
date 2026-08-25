"""topics, questions and practice sessions/turns

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name_en", sa.String(length=200), nullable=False),
        sa.Column("name_zh", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.Column("tag", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_en", name="uq_topics_name_en"),
    )
    op.create_index("ix_topics_category", "topics", ["category"])

    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("part", sa.SmallInteger(), nullable=False),
        sa.Column("content_en", sa.Text(), nullable=False),
        sa.Column("cue_card", postgresql.JSONB(), nullable=True),
        sa.Column("followup_seeds", postgresql.JSONB(), nullable=True),
        sa.Column("sort", sa.SmallInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_questions_topic_id", "questions", ["topic_id"])

    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.Enum("practice", "mock", name="session_mode", native_enum=False, length=10), nullable=False),
        sa.Column("part", sa.SmallInteger(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Enum("in_progress", "completed", "abandoned", name="session_status", native_enum=False, length=20), nullable=False),
        sa.Column("accent", sa.String(length=50), nullable=False),
        sa.Column("speed", sa.String(length=10), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_sessions_user_id", "practice_sessions", ["user_id"])

    op.create_table(
        "practice_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column("is_followup", sa.Boolean(), nullable=False),
        sa.Column("user_transcript", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.String(length=500), nullable=True),
        sa.Column("speech_events", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["practice_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_turns_session_id", "practice_turns", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_practice_turns_session_id", table_name="practice_turns")
    op.drop_table("practice_turns")
    op.drop_index("ix_practice_sessions_user_id", table_name="practice_sessions")
    op.drop_table("practice_sessions")
    op.drop_index("ix_questions_topic_id", table_name="questions")
    op.drop_table("questions")
    op.drop_index("ix_topics_category", table_name="topics")
    op.drop_table("topics")
