from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ServiceType = Literal["llm", "asr", "tts", "evaluation"]


class ApiKeySaveRequest(BaseModel):
    # 首次保存必填；已保存过 Key 后可仅更新 config（key 传空）
    key: str | None = Field(default=None, min_length=8, max_length=512)
    # 各服务专属配置：LLM 默认模型 / Region、TTS 音色等
    config: dict[str, Any] = Field(default_factory=dict)


class ApiKeyOut(BaseModel):
    service_type: ServiceType
    configured: bool
    # not_configured | unverified | valid | invalid
    status: str
    key_last4: str | None
    config: dict[str, Any]
    last_verified_at: datetime | None


class ApiKeyTestResult(BaseModel):
    service_type: ServiceType
    testable: bool
    success: bool = False
    message: str
    # user | platform | none
    key_source: str = "none"
    latency_ms: int | None = None
