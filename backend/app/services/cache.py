"""缓存抽象：优先 Redis，未配置 REDIS_URL 时回退进程内缓存。

当前用途：refresh token 白名单（jti）、登录失败限流计数。
生产环境必须配置 REDIS_URL（进程内缓存在多进程/重启场景下不可靠）。
"""

import asyncio
import time
from datetime import timedelta

import redis.asyncio as aioredis

from app.core.config import get_settings

_backend: aioredis.Redis | None = None
_memory: "_MemoryCache | None" = None
_init_lock = asyncio.Lock()


class _MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [k for k, exp in self._expiry.items() if exp <= now]
        for key in expired:
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    async def get(self, key: str) -> str | None:
        async with self._lock:
            self._purge()
            return self._data.get(key)

    async def set(self, key: str, value: str, ttl: float | None = None) -> None:
        async with self._lock:
            self._purge()
            self._data[key] = value
            if ttl is not None:
                self._expiry[key] = time.monotonic() + ttl
            else:
                self._expiry.pop(key, None)

    async def delete(self, *keys: str) -> None:
        async with self._lock:
            for key in keys:
                self._data.pop(key, None)
                self._expiry.pop(key, None)

    async def incr_with_ttl(self, key: str, ttl: float) -> int:
        async with self._lock:
            self._purge()
            value = int(self._data.get(key, "0")) + 1
            self._data[key] = str(value)
            # 首次计数时设置过期窗口，窗口内持续累加
            self._expiry.setdefault(key, time.monotonic() + ttl)
            return value


async def init_cache() -> None:
    """应用启动时调用；配置了 Redis 则建立连接并 ping 验证。"""
    global _backend, _memory
    async with _init_lock:
        if _backend is not None or _memory is not None:
            return
        redis_url = get_settings().redis_url
        if redis_url:
            client = aioredis.from_url(redis_url, decode_responses=True)
            await client.ping()
            _backend = client
        else:
            _memory = _MemoryCache()


async def close_cache() -> None:
    global _backend, _memory
    if _backend is not None:
        await _backend.aclose()
    _backend = None
    _memory = None


def _get_backend() -> aioredis.Redis | _MemoryCache:
    global _backend, _memory
    # 测试等场景可能未经 lifespan 初始化：无 Redis 配置时惰性创建内存缓存
    if _backend is None and _memory is None:
        if get_settings().redis_url:
            raise RuntimeError("Redis 已配置但未初始化，请先调用 init_cache()")
        _memory = _MemoryCache()
    return _backend if _backend is not None else _memory  # type: ignore[return-value]


def describe_backend() -> str:
    return "redis" if _backend is not None else "memory"


async def cache_get(key: str) -> str | None:
    return await _get_backend().get(key)


async def cache_set(key: str, value: str, ttl: timedelta | None = None) -> None:
    backend = _get_backend()
    if isinstance(backend, aioredis.Redis):
        await backend.set(key, value, ex=ttl)
    else:
        await backend.set(key, value, ttl=ttl.total_seconds() if ttl else None)


async def cache_delete(*keys: str) -> None:
    await _get_backend().delete(*keys)


async def cache_incr_with_ttl(key: str, ttl: timedelta) -> int:
    backend = _get_backend()
    if isinstance(backend, aioredis.Redis):
        count = await backend.incr(key)
        if count == 1:
            await backend.expire(key, int(ttl.total_seconds()))
        return count
    return await backend.incr_with_ttl(key, ttl.total_seconds())
