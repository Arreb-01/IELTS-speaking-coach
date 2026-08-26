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

    if body.key is None:
        # 仅更新服务配置，不改动已保存的 Key
        if row is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "首次配置该服务时必须填写 API Key"
            )
        row.config = body.config
        await db.commit()
        await db.refresh(row)
        return _to_out(row, service_type)

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
    row = await _get_row(db, user.id, service_type)

    if service_type == "evaluation":
        return await _test_evaluation(user, db, row)

    if service_type == "llm":
        return await _test_llm(user, db, row)

    return await _test_speech(user, db, row, service_type)


async def _test_llm(
    user: User, db: AsyncSession, row: UserApiKey | None
) -> ApiKeyTestResult:
    if row is not None:
        api_key = decrypt_secret(row.key_encrypted)
        key_source = "user"
    elif get_settings().volc_ark_default_api_key:
        api_key = get_settings().volc_ark_default_api_key
        key_source = "platform"
    else:
        return ApiKeyTestResult(
            service_type="llm", testable=True, success=False,
            message="尚未配置 API Key，且平台未提供默认 Key", key_source="none",
        )

    model = (row.config or {}).get("model") if row else None
    success, message, latency_ms = await ark.test_connection(api_key, model)

    if row is not None:
        row.status = "valid" if success else "invalid"
        row.last_verified_at = datetime.now(timezone.utc)
        await db.commit()

    return ApiKeyTestResult(
        service_type="llm", testable=True, success=success, message=message,
        key_source=key_source, latency_ms=latency_ms,
    )


async def _test_evaluation(
    user: User, db: AsyncSession, row: UserApiKey | None
) -> ApiKeyTestResult:
    """口语评测连通性测试。凭据形态与 ASR 一致：APPID + Access Token。

    未单独配置时复用用户 ASR 应用或平台默认凭据（同一语音控制台应用）。"""
    from app.services.volcengine.evaluation import (
        EvaluationCredentials,
        test_evaluation_connection,
    )
    from app.services.volcengine.speech import resolve_evaluation_credentials

    settings = get_settings()
    credentials: EvaluationCredentials | None = None
    key_source = "none"

    if row is not None:
        config = dict(row.config or {})
        appid = config.get("appid")
        token = decrypt_secret(row.key_encrypted)
        if appid and token:
            credentials = EvaluationCredentials(
                appid=str(appid),
                access_token=token,
                cluster=str(config.get("cluster") or settings.volc_evaluation_cluster),
            )
            key_source = "user"
        else:
            row.status = "invalid"
            row.last_verified_at = datetime.now(timezone.utc)
            await db.commit()
            return ApiKeyTestResult(
                service_type="evaluation", testable=True, success=False,
                message="请在配置中填写 APPID（语音控制台 → 应用管理）", key_source="user",
            )
    else:
        credentials = await resolve_evaluation_credentials(user, db)
        if credentials is not None:
            key_source = "platform"

    if credentials is None:
        return ApiKeyTestResult(
            service_type="evaluation", testable=True, success=False,
            message="尚未配置凭据，且平台未提供默认凭据", key_source=key_source,
        )

    success, message, latency_ms = await test_evaluation_connection(credentials)
    if row is not None:
        row.status = "valid" if success else "invalid"
        row.last_verified_at = datetime.now(timezone.utc)
        await db.commit()
    return ApiKeyTestResult(
        service_type="evaluation", testable=True, success=success, message=message,
        key_source=key_source, latency_ms=latency_ms,
    )


async def _test_speech(
    user: User, db: AsyncSession, row: UserApiKey | None, service_type: str
) -> ApiKeyTestResult:
    """ASR / TTS 连通性测试。凭据形态：APPID + Access Token（存 config）。"""
    from app.services.volcengine.asr import AsrCredentials, test_asr_connection
    from app.services.volcengine.speech import ASR_RESOURCE_IDS, resolve_asr_credentials
    from app.services.volcengine.tts import TtsCredentials, test_tts_connection

    settings = get_settings()

    if row is not None:
        config = dict(row.config or {})
        appid = config.get("appid")
        access_token = decrypt_secret(row.key_encrypted)
        key_source = "user"
        if not appid:
            if row is not None:
                row.status = "invalid"
                row.last_verified_at = datetime.now(timezone.utc)
                await db.commit()
            return ApiKeyTestResult(
                service_type=service_type, testable=True, success=False,
                message="请在配置中填写 APPID（语音控制台 → 应用管理）", key_source=key_source,
            )
    else:
        platform_asr = await resolve_asr_credentials(user, db) if service_type == "asr" else None
        platform_tts = None
        if service_type == "tts":
            from app.services.volcengine.speech import resolve_tts_credentials

            platform_tts = await resolve_tts_credentials(user, db)
        platform = platform_asr or platform_tts
        if platform is None:
            return ApiKeyTestResult(
                service_type=service_type, testable=True, success=False,
                message="尚未配置凭据，且平台未提供默认凭据", key_source="none",
            )
        appid = platform.appid
        access_token = platform.access_token
        key_source = "platform"

    if service_type == "asr":
        version = str((row.config or {}).get("version") or "2.0") if row else "2.0"
        credentials = AsrCredentials(
            appid=str(appid),
            access_token=access_token,
            resource_id=ASR_RESOURCE_IDS.get(version, ASR_RESOURCE_IDS["2.0"]),
        )
        success, message, latency_ms = await test_asr_connection(credentials)
    else:
        credentials = TtsCredentials(
            appid=str(appid), access_token=access_token,
            resource_id=settings.volc_tts_resource_id,
        )
        success, message, latency_ms = await test_tts_connection(credentials)

    if row is not None:
        row.status = "valid" if success else "invalid"
        row.last_verified_at = datetime.now(timezone.utc)
        await db.commit()

    return ApiKeyTestResult(
        service_type=service_type, testable=True, success=success, message=message,
        key_source=key_source, latency_ms=latency_ms,
    )
