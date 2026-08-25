"""练习引擎注册表：WS ticket 签发校验 + 引擎实例生命周期管理。

- create_ticket：REST 创建会话时签发一次性 ticket（60 秒有效）
- 引擎断线后保留 RECONNECT_TTL（5 分钟），期间重连可继续练习
- 后台任务周期清理超时的 in_progress 引擎并落库为 abandoned
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.services import cache
from app.services.practice_engine.constants import RECONNECT_TTL

logger = logging.getLogger(__name__)

_TICKET_PREFIX = "practice:ticket:"
_TICKET_TTL = timedelta(seconds=60)

# session_id -> engine
_engines: dict[uuid.UUID, "object"] = {}
# user_id -> session_id（单活动会话约束）
_user_active: dict[uuid.UUID, uuid.UUID] = {}

_sweeper: asyncio.Task | None = None


async def issue_ticket(session_id: uuid.UUID) -> str:
    """签发一次性 WS ticket（立即写入缓存，避免竞态）。"""
    ticket = uuid.uuid4().hex
    await cache.cache_set(f"{_TICKET_PREFIX}{ticket}", str(session_id), ttl=_TICKET_TTL)
    return ticket


async def consume_ticket(ticket: str) -> uuid.UUID | None:
    key = f"{_TICKET_PREFIX}{ticket}"
    value = await cache.cache_get(key)
    if value is None:
        return None
    await cache.cache_delete(key)
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def register(engine) -> None:
    _engines[engine.session.id] = engine
    _user_active[engine.user.id] = engine.session.id


def get_engine(session_id: uuid.UUID):
    return _engines.get(session_id)


def detach(session_id: uuid.UUID) -> None:
    engine = _engines.pop(session_id, None)
    if engine is not None:
        active = _user_active.get(engine.user.id)
        if active == session_id:
            _user_active.pop(engine.user.id, None)


def active_session_of(user_id) -> uuid.UUID | None:
    return _user_active.get(user_id)


def start_sweeper() -> None:
    global _sweeper
    if _sweeper is None or _sweeper.done():
        _sweeper = asyncio.create_task(_sweep_loop())


def stop_sweeper() -> None:
    global _sweeper
    if _sweeper is not None:
        _sweeper.cancel()
        _sweeper = None


async def _sweep_loop() -> None:
    """周期回收：断线超时或会话总时长超限的引擎。"""
    import time

    while True:
        try:
            await asyncio.sleep(30)
            now = time.monotonic()
            for session_id, engine in list(_engines.items()):
                # 已结束的引擎直接移除
                if engine._closed:
                    detach(session_id)
                    continue
                idle = now - engine.last_activity
                if idle > RECONNECT_TTL.total_seconds():
                    logger.info("练习会话 %s 重连超时，标记为 abandoned", session_id)
                    engine._closed = True
                    await _abandon_in_db(session_id)
                    detach(session_id)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("练习引擎清理任务异常")


async def _abandon_in_db(session_id: uuid.UUID) -> None:
    from app.db.base import async_session_factory
    from app.db.models import PracticeSession

    try:
        async with async_session_factory() as db:
            session = await db.get(PracticeSession, session_id)
            if session is not None and session.status == "in_progress":
                session.status = "abandoned"
                session.ended_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception:
        logger.exception("落库 abandoned 状态失败：%s", session_id)
