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
