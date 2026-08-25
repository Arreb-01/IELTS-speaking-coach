"""数据库引擎、会话与声明基类。"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    # SQLite（本地测试）不支持 pool_pre_ping 之外的一些 PG 参数，按方言区分
    url = get_settings().database_url
    if url.startswith("sqlite"):
        return {}
    return {"pool_pre_ping": True}


engine = create_async_engine(get_settings().database_url, **_engine_kwargs())
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
