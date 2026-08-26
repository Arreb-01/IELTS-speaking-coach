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


# ---------------------------------------------------------------------------
# WebSocket 练习流程测试环境
# 文件型 SQLite：先在 pytest 事件循环建库+种子数据，之后 TestClient 的
# portal 事件循环用新引擎连同一个文件（跨循环顺序使用，无并发共享）。
# ---------------------------------------------------------------------------

WS_TEST_TOPICS = [
    {
        "name_en": "Home & Accommodation",
        "name_zh": "家与住所",
        "category": "home",
        "tag": "must",
        "questions": [
            "Do you live in a house or an apartment?",
            "What do you like most about the place where you live?",
            "Would you like to move to a different place in the future? Why?",
            "How is your neighbourhood changing?",
        ],
    },
    {
        "name_en": "A Person Who Has Inspired You",
        "name_zh": "激励过你的人",
        "category": "person",
        "tag": "must",
        "cue_card": {
            "prompt": "Describe a person who has inspired you.",
            "summary_zh": "描述一个激励过你的人。",
            "you_should_say": ["who this person is", "how you know this person"],
        },
        "followup_seeds": ["What qualities make someone a good role model?"],
    },
]


async def seed_ws_topics(factory) -> dict:
    """向测试库写入两个话题，返回 {name_en: topic_id}。"""
    import uuid as uuid_mod

    from app.db.models import Question, Topic

    ids = {}
    async with factory() as db:
        for item in WS_TEST_TOPICS:
            topic = Topic(
                name_en=item["name_en"],
                name_zh=item["name_zh"],
                category=item["category"],
                tag=item["tag"],
            )
            db.add(topic)
            await db.flush()
            ids[item["name_en"]] = str(topic.id)
            if "questions" in item:
                for i, text in enumerate(item["questions"]):
                    db.add(Question(topic_id=topic.id, part=1, content_en=text, sort=i))
            else:
                db.add(
                    Question(
                        topic_id=topic.id,
                        part=2,
                        content_en=item["cue_card"]["prompt"],
                        cue_card=item["cue_card"],
                        sort=0,
                    )
                )
                db.add(Question(topic_id=topic.id, part=3, content_en=item["followup_seeds"][0], sort=0))
        await db.commit()
    return ids


@pytest_asyncio.fixture
async def ws_db(tmp_path):
    """预置话题的文件型 SQLite 测试库，返回 (db_path, topic_ids)。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base
    from app.db import models  # noqa: F401

    db_path = tmp_path / "ws_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    topic_ids = await seed_ws_topics(factory)
    await engine.dispose()
    return db_path, topic_ids


@pytest.fixture
def ws_client(ws_db, tmp_path, monkeypatch):
    """同步 TestClient：WebSocket 全流程测试（独立于 httpx 异步夹具）。"""
    from starlette.testclient import TestClient

    from app.db.base import Base, get_db
    from app.main import app
    from app.services import cache
    from app.services import practice_engine as pe_pkg
    from app.services.practice_engine import registry

    db_path, _ = ws_db
    monkeypatch.setattr(get_settings(), "volc_mock", True)
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path / "storage"))
    monkeypatch.setattr(get_settings(), "redis_url", None)
    monkeypatch.setattr(get_settings(), "volc_ark_default_api_key", None)
    cache._backend = None
    cache._memory = None

    state: dict = {}

    async def override_get_db():
        if "factory" not in state:
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
            state["engine"] = engine
            state["factory"] = async_sessionmaker(engine, expire_on_commit=False)
        async with state["factory"]() as session:
            yield session

    def lazy_factory():
        return state["factory"]()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(pe_pkg.engine, "async_session_factory", lazy_factory)
    monkeypatch.setattr("app.db.base.async_session_factory", lazy_factory)
    monkeypatch.setattr("app.api.v1.ws.async_session_factory", lazy_factory)
    monkeypatch.setattr("app.services.scoring.engine.async_session_factory", lazy_factory)

    registry._engines.clear()
    registry._user_active.clear()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()
    registry._engines.clear()
    registry._user_active.clear()
