"""测试夹具：SQLite 内存库 + 进程内缓存，不依赖 Docker/PG/Redis。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base, get_db
from app.main import app
from app.services import cache


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    """强制测试运行在无 Redis、无平台默认 Key 的隔离配置下。"""
    monkeypatch.setattr(get_settings(), "redis_url", None)
    monkeypatch.setattr(get_settings(), "volc_ark_default_api_key", None)
    cache._backend = None
    cache._memory = None
    yield
    cache._backend = None
    cache._memory = None


@pytest.fixture
async def db_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def auth_headers(client):
    """注册一个测试用户并返回 Authorization 头。"""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "tester@example.com", "password": "pass1234", "nickname": "测试考生"},
    )
    assert resp.status_code == 201, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
