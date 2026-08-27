"""ORM 模型：用户与用户 API Key（BYOK）。

config 字段使用 JSON 类型：PostgreSQL 上渲染为 JSONB，SQLite（本地测试）
上渲染为 JSON，保证跨方言可用。
"""

import uuid
from datetime import date, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")

SERVICE_TYPES = ("llm", "asr", "tts", "evaluation")
# not_configured 仅作为 API 响应中的虚拟状态（无对应数据库行），不落库
KEY_STATUSES = ("unverified", "valid", "invalid")

PART_TYPES = (1, 2, 3)
TOPIC_TAGS = ("new", "retained", "must")
SESSION_MODES = ("practice", "mock")
SESSION_STATUSES = ("in_progress", "completed", "abandoned")
REPORT_STATUSES = ("pending", "processing", "completed", "failed")
TASK_TYPES = ("topic", "special", "corpus")
TASK_STATUSES = ("pending", "done", "skipped")
# 四维能力维度（score_reports 列名，弱项分析/任务定向用）
SKILL_DIMENSIONS = ("fluency", "lexical", "grammar", "pronunciation")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(sa.String(255))
    nickname: Mapped[str | None] = mapped_column(sa.String(50))
    # 预留：手机号注册后续版本接入短信服务时启用
    phone: Mapped[str | None] = mapped_column(sa.String(20))
    # 目标分数，如 6.5 / 7.0
    target_band: Mapped[float | None] = mapped_column(sa.Numeric(2, 1))
    # 完成初始能力测评的时间（NULL=未测评，Dashboard 显示测评引导）
    placement_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class UserApiKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (sa.UniqueConstraint("user_id", "service_type", name="uq_user_service"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    service_type: Mapped[str] = mapped_column(
        sa.Enum("llm", "asr", "tts", "evaluation", name="api_key_service_type", native_enum=False, length=20)
    )
    # AES-256-GCM 加密后的 Key 密文
    key_encrypted: Mapped[str] = mapped_column(sa.Text)
    key_last4: Mapped[str] = mapped_column(sa.String(4))
    # 各服务专属配置（LLM 默认模型、TTS 音色、Region 等）
    config: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict)
    status: Mapped[str] = mapped_column(
        sa.Enum("unverified", "valid", "invalid", name="api_key_status", native_enum=False, length=20),
        default="unverified",
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


class Topic(Base):
    """雅思口语话题。Part D 导入完整题库后本表批量扩充。"""

    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    name_en: Mapped[str] = mapped_column(sa.String(200))
    name_zh: Mapped[str | None] = mapped_column(sa.String(200))
    # Part1：主题（Home / Music / Study...）；Part2&3：人物/事件/事物/地点
    category: Mapped[str | None] = mapped_column(sa.String(50), index=True)
    # new 新题 / retained 保留题 / must 必考题
    tag: Mapped[str | None] = mapped_column(sa.String(20))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )

    __table_args__ = (sa.UniqueConstraint("name_en", name="uq_topics_name_en"),)


class Question(Base):
    """话题下的题目。Part2 的 Cue Card 内容存在 cue_card JSONB。"""

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    part: Mapped[int] = mapped_column(sa.SmallInteger)  # 1 / 2 / 3
    content_en: Mapped[str] = mapped_column(sa.Text)
    # Part2 Cue Card：{"prompt": "...", "you_should_say": ["...", ...], "summary_zh": "..."}
    cue_card: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    # Part3 追问种子（供 LLM 生成深度问题时参考）
    followup_seeds: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    sort: Mapped[int] = mapped_column(sa.SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class PracticeSession(Base):
    """一次练习/模考会话。"""

    __tablename__ = "practice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(
        sa.Enum("practice", "mock", name="session_mode", native_enum=False, length=10),
        default="practice",
    )
    part: Mapped[int] = mapped_column(sa.SmallInteger)  # 1 / 2 / 3
    topic_id: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("topics.id", ondelete="SET NULL"))
    # 能力测评专用：预选题的 question_id 列表（普通练习为 NULL，按 topic 查题）
    question_ids: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    status: Mapped[str] = mapped_column(
        sa.Enum("in_progress", "completed", "abandoned", name="session_status", native_enum=False, length=20),
        default="in_progress",
    )
    # 考官设置：英音/美音音色键 + 语速键（slow/normal/fast）
    accent: Mapped[str] = mapped_column(sa.String(50), default="en_female_anna")
    speed: Mapped[str] = mapped_column(sa.String(10), default="normal")
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class PracticeTurn(Base):
    """一个作答轮次：考官问题 + 用户回答转写 + 音频归档。"""

    __tablename__ = "practice_turns"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("practice_sessions.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(sa.SmallInteger)
    question_text: Mapped[str | None] = mapped_column(sa.Text)
    is_followup: Mapped[bool] = mapped_column(default=False)
    user_transcript: Mapped[str | None] = mapped_column(sa.Text)
    # 归档音频相对路径（StorageService 管理）
    audio_path: Mapped[str | None] = mapped_column(sa.String(500))
    # 前端 VAD 事件（停顿/发言时段），Part C 流利度分析数据
    speech_events: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class ScoreReport(Base):
    """一次练习会话的评分报告（rescore 原地更新，session 唯一）。"""

    __tablename__ = "score_reports"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("practice_sessions.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(
        sa.Enum("pending", "processing", "completed", "failed", name="report_status", native_enum=False, length=20),
        default="pending",
    )
    # 四维 band（0-9 步长 0.5）+ 综合
    overall_band: Mapped[float | None] = mapped_column(sa.Numeric(2, 1))
    fluency: Mapped[float | None] = mapped_column(sa.Numeric(2, 1))
    lexical: Mapped[float | None] = mapped_column(sa.Numeric(2, 1))
    grammar: Mapped[float | None] = mapped_column(sa.Numeric(2, 1))
    pronunciation: Mapped[float | None] = mapped_column(sa.Numeric(2, 1))
    # 流利度规则引擎原始统计（wpm/停顿/填充词）
    fluency_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    overall_comment_zh: Mapped[str | None] = mapped_column(sa.Text)
    strengths: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    improvements: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    # 高分表达替换 [{original, upgraded, note_zh?}]
    expression_upgrades: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    # 低置信度标注（回答过短/音频质量差/四维极差>2）
    low_confidence: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    # 生成链路用到的模型/服务版本，回归排查用
    model_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    error: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class TurnAnalysis(Base):
    """报告下的逐轮分析：句子级问题标注 + 发音评测明细。"""

    __tablename__ = "turn_analyses"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("score_reports.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid())
    seq: Mapped[int] = mapped_column(sa.SmallInteger)
    # [{text, issues: [{type, severity, explanation_zh, suggestion}]}]
    sentences: Mapped[list[Any] | None] = mapped_column(JSONVariant)
    # 火山口语评测原始返回（词级分数等，服务支持时）
    pronunciation_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    # 命中的填充词 [{word, count}]
    filler_hits: Mapped[list[Any] | None] = mapped_column(JSONVariant)


class SampleAnswer(Base):
    """范文：P1 挂 question 级；P2 挂 topic 级（question_id 空）；linked 为串联共享范文。"""

    __tablename__ = "sample_answers"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    part: Mapped[int] = mapped_column(sa.SmallInteger)
    text_en: Mapped[str] = mapped_column(sa.Text)
    summary_zh: Mapped[str | None] = mapped_column(sa.Text)
    # p1 / p2p3 / linked
    source: Mapped[str] = mapped_column(sa.String(20))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class TopicLink(Base):
    """Part 2 串联：一份共享范文适配的多个话题。"""

    __tablename__ = "topic_links"
    __table_args__ = (sa.UniqueConstraint("group_name", "topic_id", name="uq_topic_links_group_topic"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    group_name: Mapped[str] = mapped_column(sa.String(200))
    shared_answer_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("sample_answers.id", ondelete="CASCADE")
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    note: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class Expression(Base):
    """话题高分表达（导入时从范文 LLM 提取）。"""

    __tablename__ = "expressions"
    __table_args__ = (sa.UniqueConstraint("topic_id", "text_en", name="uq_expressions_topic_text"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("topics.id", ondelete="CASCADE"), index=True
    )
    text_en: Mapped[str] = mapped_column(sa.String(500))
    meaning_zh: Mapped[str] = mapped_column(sa.String(500))
    example_en: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class UserVocabWord(Base):
    """个人词汇本：从高分表达收藏，或练习中积累。"""

    __tablename__ = "user_vocab_words"
    __table_args__ = (sa.UniqueConstraint("user_id", "word", name="uq_user_vocab_words_user_word"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    word: Mapped[str] = mapped_column(sa.String(200))
    # 来源句（表达的原句例句）
    context_en: Mapped[str | None] = mapped_column(sa.Text)
    source_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("topics.id", ondelete="SET NULL")
    )
    is_favorite: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class MistakeNote(Base):
    """错题本：数据来自评分的逐句分析（Part C 链路接入）。"""

    __tablename__ = "mistake_notes"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid())
    issue_type: Mapped[str] = mapped_column(sa.String(30))
    severity: Mapped[str] = mapped_column(sa.String(10))
    original: Mapped[str | None] = mapped_column(sa.Text)
    suggestion: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class DailyTask(Base):
    """学习路径的单日任务（规则引擎生成，文案生成时固化）。

    - plan_date：任务所属日（用户本地时区日期）
    - task_type：topic 话题练习 / special 发音专项跟读 / corpus 表达学习
    - 幂等策略：同日重跑删除 pending，保留 done/skipped
    """

    __tablename__ = "daily_tasks"
    __table_args__ = (sa.Index("ix_daily_tasks_user_date", "user_id", "plan_date"),)

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE")
    )
    plan_date: Mapped[date] = mapped_column(sa.Date)
    task_type: Mapped[str] = mapped_column(
        sa.Enum(*TASK_TYPES, name="daily_task_type", native_enum=False, length=20)
    )
    # 针对的弱项维度（fluency/lexical/grammar/pronunciation）
    dimension: Mapped[str | None] = mapped_column(sa.String(20))
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("topics.id", ondelete="SET NULL")
    )
    part: Mapped[int | None] = mapped_column(sa.SmallInteger)
    title_zh: Mapped[str] = mapped_column(sa.String(100))
    desc_zh: Mapped[str] = mapped_column(sa.String(200))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    status: Mapped[str] = mapped_column(
        sa.Enum(*TASK_STATUSES, name="daily_task_status", native_enum=False, length=20),
        default="pending",
    )
    sort: Mapped[int] = mapped_column(sa.SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
