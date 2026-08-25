"""全局配置：从环境变量 / backend/.env 读取。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IELTS Speaking Coach"
    env: str = "dev"  # dev / prod
    api_v1_prefix: str = "/api/v1"

    # 数据库与缓存
    database_url: str = (
        "postgresql+asyncpg://ielts:ielts_dev_password@localhost:5432/ielts_coach"
    )
    # 未配置 REDIS_URL 时回退进程内缓存（仅限本地开发；生产必须配置）
    redis_url: str | None = None

    # 安全
    # JWT 签名密钥；生产必填。生成方式：python -c "import secrets; print(secrets.token_hex(32))"
    secret_key: str | None = None
    # API Key 加密主密钥（AES-256-GCM，64 位 hex = 32 字节）；生产必填
    api_key_encryption_key: str | None = None
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    login_rate_limit: int = 5  # 同一邮箱窗口期内允许的连续登录失败次数
    login_rate_window_minutes: int = 15

    # 火山引擎方舟（豆包 LLM）。平台默认 Key：用户未配置 BYOK Key 时回退使用。
    volc_ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    volc_ark_default_api_key: str | None = None
    volc_ark_test_model: str = "doubao-1.5-pro-32k-250115"

    # 逗号分隔的跨域来源
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
