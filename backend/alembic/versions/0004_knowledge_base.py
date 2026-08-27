"""knowledge base: sample_answers, topic_links, expressions, user_vocab_words, mistake_notes

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json() -> sa.types.TypeEngine:
    from app.db.models import JSONVariant

    return JSONVariant


def upgrade() -> None:
    op.create_table(
        "sample_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=True),
        sa.Column("part", sa.SmallInteger(), nullable=False),
        sa.Column("text_en", sa.Text(), nullable=False),
        sa.Column("summary_zh", sa.Text(), nullable=True),
        # p1 / p2p3 / linked
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sample_answers_topic_id", "sample_answers", ["topic_id"])
    op.create_index("ix_sample_answers_question_id", "sample_answers", ["question_id"])

    op.create_table(
        "topic_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_name", sa.String(200), nullable=False),
        sa.Column("shared_answer_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["shared_answer_id"], ["sample_answers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_name", "topic_id", name="uq_topic_links_group_topic"),
    )
    op.create_index("ix_topic_links_topic_id", "topic_links", ["topic_id"])

    op.create_table(
        "expressions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=False),
        sa.Column("text_en", sa.String(500), nullable=False),
        sa.Column("meaning_zh", sa.String(500), nullable=False),
        sa.Column("example_en", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", "text_en", name="uq_expressions_topic_text"),
    )
    op.create_index("ix_expressions_topic_id", "expressions", ["topic_id"])

    op.create_table(
        "user_vocab_words",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("word", sa.String(200), nullable=False),
        sa.Column("context_en", sa.Text(), nullable=True),
        sa.Column("source_topic_id", sa.Uuid(), nullable=True),
        sa.Column("is_favorite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_topic_id"], ["topics.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "word", name="uq_user_vocab_words_user_word"),
    )
    op.create_index("ix_user_vocab_words_user_id", "user_vocab_words", ["user_id"])

    # 占位空表：数据由 Part C 逐句分析写入（Part D 只建结构）
    op.create_table(
        "mistake_notes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("turn_id", sa.Uuid(), nullable=True),
        sa.Column("issue_type", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("original", sa.Text(), nullable=True),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_mistake_notes_user_id", "mistake_notes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mistake_notes_user_id", table_name="mistake_notes")
    op.drop_table("mistake_notes")
    op.drop_index("ix_user_vocab_words_user_id", table_name="user_vocab_words")
    op.drop_table("user_vocab_words")
    op.drop_index("ix_expressions_topic_id", table_name="expressions")
    op.drop_table("expressions")
    op.drop_index("ix_topic_links_topic_id", table_name="topic_links")
    op.drop_table("topic_links")
    op.drop_index("ix_sample_answers_question_id", table_name="sample_answers")
    op.drop_index("ix_sample_answers_topic_id", table_name="sample_answers")
    op.drop_table("sample_answers")
