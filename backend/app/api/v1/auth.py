"""认证：注册 / 登录（带限流）/ 刷新 / 登出 / 当前用户。"""

import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.base import get_db
from app.db.models import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services import cache

router = APIRouter()


def _refresh_cache_key(jti: str) -> str:
    return f"auth:refresh:{jti}"


def _login_fail_key(email: str) -> str:
    return f"auth:login_fail:{email}"


async def _issue_tokens(user: User) -> TokenResponse:
    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    payload = decode_token(refresh, REFRESH_TOKEN_TYPE)
    settings = get_settings()
    await cache.cache_set(
        _refresh_cache_key(payload["jti"]),
        str(user.id),
        ttl=timedelta(days=settings.refresh_token_expire_days),
    )
    return TokenResponse(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


def _default_nickname(email: str) -> str:
    return email.split("@", 1)[0][:50] or "考生"


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    email = body.email.lower()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "该邮箱已注册，请直接登录")
    user = User(
        email=email,
        hashed_password=hash_password(body.password),
        nickname=body.nickname or _default_nickname(email),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await _issue_tokens(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    email = body.email.lower()
    fail_key = _login_fail_key(email)
    window = timedelta(minutes=settings.login_rate_window_minutes)

    failures = int(await cache.cache_get(fail_key) or 0)
    if failures >= settings.login_rate_limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"登录失败次数过多，请约 {settings.login_rate_window_minutes} 分钟后再试",
        )

    user = await db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.hashed_password):
        await cache.cache_incr_with_ttl(fail_key, window)
        remaining = max(settings.login_rate_limit - failures - 1, 0)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "邮箱或密码错误" + (f"，剩余尝试次数 {remaining}" if remaining else ""),
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")

    await cache.cache_delete(fail_key)
    return await _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        payload = decode_token(body.refresh_token, REFRESH_TOKEN_TYPE)
        jti = payload["jti"]
        user_id = uuid.UUID(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "无效的刷新凭证")

    stored_user_id = await cache.cache_get(_refresh_cache_key(jti))
    if stored_user_id != str(user_id):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新凭证已失效，请重新登录")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已被禁用")

    # 轮换：旧 refresh token 立即作废
    await cache.cache_delete(_refresh_cache_key(jti))
    return await _issue_tokens(user)


@router.post("/logout")
async def logout(body: RefreshRequest) -> dict[str, str]:
    try:
        payload = decode_token(body.refresh_token, REFRESH_TOKEN_TYPE)
    except jwt.InvalidTokenError:
        # 幂等：无效 token 的登出也返回成功
        return {"detail": "已登出"}
    await cache.cache_delete(_refresh_cache_key(payload.get("jti", "")))
    return {"detail": "已登出"}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
