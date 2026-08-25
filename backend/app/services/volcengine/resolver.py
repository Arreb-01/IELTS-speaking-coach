"""BYOK Key 解析：用户自带 Key 优先，未配置时回退平台默认 Key。

Part B/C 的所有 AI 服务调用（ASR/TTS/评测/LLM）统一经由本解析器获取凭据，
保证 BYOK 优先级在全系统内一致。
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_secret
from app.db.models import User, UserApiKey


async def resolve_ark_credentials(
    user: User, db: AsyncSession
) -> tuple[str | None, str]:
    """返回 (api_key, key_source)；key_source 为 'user' | 'platform'。"""
    row = await db.scalar(
        select(UserApiKey).where(
            UserApiKey.user_id == user.id,
            UserApiKey.service_type == "llm",
        )
    )
    if row is not None:
        return decrypt_secret(row.key_encrypted), "user"
    return get_settings().volc_ark_default_api_key, "platform"
