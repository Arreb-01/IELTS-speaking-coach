"""用户 API Key（BYOK）管理：保存 / 查询 / 删除 / 连通性测试。

安全约束：
- Key 以 AES-256-GCM 加密落库，接口只返回后四位；
- 任何日志、响应中不出现完整 Key 明文；
- 每类服务独立配置，优先级：用户 Key > 平台默认 Key。
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret
from app.db.base import get_db
from app.db.models import SERVICE_TYPES, User, UserApiKey
from app.schemas.api_key import ApiKeyOut, ApiKeySaveRequest, ApiKeyTestResult, ServiceType
from app.services import cache
from app.services.volcengine import ark

router = APIRouter()


def _to_out(row: UserApiKey | None, service_type: str) -> ApiKeyOut:
    if row is None:
        return ApiKeyOut(
            service_type=service_type,
            configured=False,
            status="not_configured",
            key_last4=None,
            config={},
            last_verified_at=None,
        )
    return ApiKeyOut(
        service_type=service_type,
        configured=True,
        status=row.status,
        key_last4=row.key_last4,
        config=row.config or {},
        last_verified_at=row.last_verified_at,
    )


async def _get_row(
    db: AsyncSession, user_id, service_type: str
) -> UserApiKey | None:
    return await db.scalar(
        select(UserApiKey).where(
            UserApiKey.user_id == user_id,
            UserApiKey.service_type == service_type,
        )
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyOut]:
    rows = {
        row.service_type: row
        for row in await db.scalars(
            select(UserApiKey).where(UserApiKey.user_id == user.id)
        )
    }
    return [_to_out(rows.get(st), st) for st in SERVICE_TYPES]


@router.put("/{service_type}", response_model=ApiKeyOut)
async def save_api_key(
    service_type: ServiceType,
    body: ApiKeySaveRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyOut:
    row = await _get_row(db, user.id, service_type)
    key = body.key.strip()
    if row is None:
        row = UserApiKey(user_id=user.id, service_type=service_type)
        db.add(row)
    row.key_encrypted = encrypt_secret(key)
    row.key_last4 = key[-4:]
    row.config = body.config
    row.status = "unverified"
    row.last_verified_at = None
    await db.commit()
    await db.refresh(row)
    return _to_out(row, service_type)


@router.delete("/{service_type}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    service_type: ServiceType,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _get_row(db, user.id, service_type)
    if row is not None:
        await db.delete(row)
        await db.commit()


@router.post("/{service_type}/test", response_model=ApiKeyTestResult)
async def test_api_key(
    service_type: ServiceType,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyTestResult:
    if service_type != "llm":
        # ASR/TTS/口语评测的凭据形态（AccessKey 对等）随 Part B/C 语音模块接入定型
        return ApiKeyTestResult(
            service_type=service_type,
            testable=False,
            message="该服务的连通性测试将在语音模块上线后开放",
        )

    row = await _get_row(db, user.id, "llm")
    if row is not None:
        api_key = decrypt_secret(row.key_encrypted)
        key_source = "user"
    elif get_settings().volc_ark_default_api_key:
        api_key = get_settings().volc_ark_default_api_key
        key_source = "platform"
    else:
        return ApiKeyTestResult(
            service_type="llm",
            testable=True,
            success=False,
            message="尚未配置 API Key，且平台未提供默认 Key",
            key_source="none",
        )

    model = (row.config or {}).get("model") if row else None
    success, message, latency_ms = await ark.test_connection(api_key, model)

    if row is not None:
        row.status = "valid" if success else "invalid"
        row.last_verified_at = datetime.now(timezone.utc)
        await db.commit()

    return ApiKeyTestResult(
        service_type="llm",
        testable=True,
        success=success,
        message=message,
        key_source=key_source,
        latency_ms=latency_ms,
    )
