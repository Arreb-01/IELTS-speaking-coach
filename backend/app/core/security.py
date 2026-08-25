"""密码哈希与 JWT 签发/校验。"""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def _jwt_secret() -> str:
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key
    if settings.env == "dev":
        # 本地开发缺省密钥，仅避免启动失败；生产环境必须在 .env 中显式配置
        return "ielts-coach-dev-jwt-secret-override-me-in-production"
    raise RuntimeError("生产环境必须配置 SECRET_KEY")


def _create_token(user_id: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict:
    """校验并解析 JWT。类型不匹配或过期/伪造均抛 jwt.InvalidTokenError 系异常。"""
    payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("token 类型不匹配")
    return payload


def create_access_token(user_id) -> str:
    settings = get_settings()
    return _create_token(
        str(user_id), ACCESS_TOKEN_TYPE,
        timedelta(minutes=settings.access_token_expire_minutes),
    )


def create_refresh_token(user_id) -> str:
    settings = get_settings()
    return _create_token(
        str(user_id), REFRESH_TOKEN_TYPE,
        timedelta(days=settings.refresh_token_expire_days),
    )
