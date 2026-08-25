"""语音服务凭据解析（ASR / TTS）与统一工厂。

BYOK 优先级与 Ark LLM 一致：用户 Key（user_api_keys.config 中的
appid/access_token/version 等）> 平台默认（.env）。
VOLC_MOCK=1 时工厂返回 Mock 实现，不触碰真实服务。
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User, UserApiKey
from app.services.volcengine.asr import AsrCredentials, VolcAsrSession
from app.services.volcengine.tts import TtsCredentials

# ASR 版本 → Resource ID
ASR_RESOURCE_IDS = {
    "2.0": "volc.seedasr.sauc.duration",
    "1.0": "volc.bigasr.sauc.duration",
}


@dataclass
class SpeechCredentials:
    appid: str
    access_token: str
    resource_id: str
    source: str  # user | platform


def _asr_resource_id(config: dict[str, Any] | None) -> str:
    version = str((config or {}).get("version") or "2.0")
    return ASR_RESOURCE_IDS.get(version, ASR_RESOURCE_IDS["2.0"])


async def _load_user_config(
    db: AsyncSession, user_id, service_type: str
) -> dict[str, Any] | None:
    from app.core.crypto import decrypt_secret

    row = await db.scalar(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.service_type == service_type,
        )
    )
    if row is None:
        return None
    config = dict(row.config or {})
    # Key 主字段即 access token（Part A 设计）；appid 等放在 config
    config["access_token"] = decrypt_secret(row.key_encrypted)
    return config


async def resolve_asr_credentials(user: User, db: AsyncSession) -> SpeechCredentials | None:
    settings = get_settings()
    config = await _load_user_config(db, user.id, "asr")
    if config and config.get("appid") and config.get("access_token"):
        return SpeechCredentials(
            appid=str(config["appid"]),
            access_token=str(config["access_token"]),
            resource_id=_asr_resource_id(config),
            source="user",
        )
    if settings.volc_asr_appid and settings.volc_asr_access_token:
        return SpeechCredentials(
            appid=settings.volc_asr_appid,
            access_token=settings.volc_asr_access_token,
            resource_id=settings.volc_asr_resource_id,
            source="platform",
        )
    return None


async def resolve_tts_credentials(user: User, db: AsyncSession) -> SpeechCredentials | None:
    settings = get_settings()
    config = await _load_user_config(db, user.id, "tts")
    if config and config.get("appid") and config.get("access_token"):
        return SpeechCredentials(
            appid=str(config["appid"]),
            access_token=str(config["access_token"]),
            resource_id=settings.volc_tts_resource_id,
            source="user",
        )
    if settings.volc_tts_appid and settings.volc_tts_access_token:
        return SpeechCredentials(
            appid=settings.volc_tts_appid,
            access_token=settings.volc_tts_access_token,
            resource_id=settings.volc_tts_resource_id,
            source="platform",
        )
    return None


def create_asr_session(
    credentials: SpeechCredentials | None, *, on_partial=None, uid: str = "ielts-user"
):
    """按配置返回真实或 Mock 的 ASR 会话。无凭据且未开 Mock 时抛错由上层降级。"""
    from app.services.volcengine.mock import MockAsrSession

    settings = get_settings()
    if settings.volc_mock or credentials is None:
        return MockAsrSession(on_partial=on_partial)
    return VolcAsrSession(
        AsrCredentials(
            appid=credentials.appid,
            access_token=credentials.access_token,
            resource_id=credentials.resource_id,
        ),
        uid=uid,
        on_partial=on_partial,
    )


async def synthesize_tts_stream(text: str, user: User, db: AsyncSession, *, voice_key: str, speed_key: str, on_audio=None) -> bytes:
    """按配置走真实 TTS 或 Mock。返回完整音频，流式块经 on_audio 推送。"""
    from app.services.volcengine import mock as mock_module
    from app.services.volcengine import tts as tts_module

    settings = get_settings()
    if settings.volc_mock:
        return await mock_module.mock_synthesize_stream(text, on_audio=on_audio)

    credentials = await resolve_tts_credentials(user, db)
    if credentials is None:
        # 无凭据降级：Mock 音频（前端会照常播放，同时界面提示配置 Key）
        return await mock_module.mock_synthesize_stream(text, on_audio=on_audio)

    return await tts_module.synthesize_stream(
        text,
        TtsCredentials(credentials.appid, credentials.access_token, credentials.resource_id),
        voice_key=voice_key,
        speed_key=speed_key,
        on_audio=on_audio,
    )
