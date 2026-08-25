"""ORM 模型：用户与用户 API Key（BYOK）。

config 字段使用 JSON 类型：PostgreSQL 上渲染为 JSONB，SQLite（本地测试）
上渲染为 JSON，保证跨方言可用。
"""

import uuid
from datetime import datetime
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
