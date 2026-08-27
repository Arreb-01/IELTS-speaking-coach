"""Part E 链路测试：placement 测评 → 报告 → 路径生成 → Dashboard 聚合。"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import DailyTask, PracticeSession, Question, ScoreReport, Topic, User
from app.services.progress import recommender

# ---------------------------------------------------------------------------
# 夹具：内存库 + 种子白名单话题（与真实题库同名，走同一白名单逻辑）
# ---------------------------------------------------------------------------

PLACEMENT_SEED = [
    ("Hometown", [
        "Where is your hometown?",
        "What do you like about your hometown?",
        "Has your hometown changed much?",
        "Do you plan to live there in the future?",
    ]),
    ("Work & Study", [
        "Do you work or are you a student?",
        "What do you find most interesting in your studies?",
    ]),
    ("Travelling", ["Do you like travelling?", "How often do you travel?"]),
    ("Home & Accommodation", [
        "Do you live in a house or an apartment?",
        "What can you see from your window?",
    ]),
    ("The area you live in", [
        "Do you like the area where you live?",
        "Is there anything to do in your area?",
    ]),
]


async def seed_topics(factory) -> None:
    async with factory() as db:
        for name_en, questions in PLACEMENT_SEED:
            topic = Topic(
                name_en=name_en,
                name_zh=f"{name_en}（测试）",
                category="test",
                tag="must",
            )
            db.add(topic)
            await db.flush()
            for i, text in enumerate(questions):
                db.add(Question(topic_id=topic.id, part=1, content_en=text, sort=i))
        # 一个 retained P2 话题（fluency 独白候选）
        p2 = Topic(name_en="A Happy Memory", name_zh="开心的回忆", category="event", tag="retained")
        db.add(p2)
        await db.flush()
        db.add(
            Question(
                topic_id=p2.id,
                part=2,
                content_en="Describe a happy memory.",
                cue_card={"prompt": "Describe a happy memory.", "you_should_say": []},
                sort=0,
            )
        )
        await db.commit()


@pytest_asyncio.fixture
async def plan_factory(db_engine):
    """让 recommender 的全局 session 工厂指向测试库。"""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    yield factory


@pytest.fixture
def patch_recommender_db(monkeypatch, plan_factory):
    monkeypatch.setattr(recommender, "async_session_factory", plan_factory)


@pytest.fixture
async def seeded_client(client, patch_recommender_db, db_session, plan_factory):
    await seed_topics(plan_factory)
    return client


async def _register(client, email="e2e@example.com"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pass1234", "nickname": "进度考生"},
    )
    assert resp.status_code == 201, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# 测评链路
# ---------------------------------------------------------------------------

async def test_placement_start_creates_preset_session(seeded_client, plan_factory):
    headers = await _register(seeded_client)
    resp = await seeded_client.post("/api/v1/placement/start", headers=headers)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["total_questions"] == 5  # 白名单 8 题取满 5
    assert len(data["ws_path"]) > 0

    # 会话为 part1 / topic None / question_ids 固化
    factory = plan_factory
    async with factory() as db:
        session = await db.get(PracticeSession, uuid.UUID(data["session_id"]))
        assert session.topic_id is None
        assert len(session.question_ids) == 5
        from sqlalchemy import func, select

        count = await db.scalar(
            select(func.count())
            .select_from(Question)
            .where(Question.id.in_([uuid.UUID(q) for q in session.question_ids]))
        )
        assert count == 5


async def test_placement_repeat_start_abandons_previous(seeded_client, plan_factory):
    headers = await _register(seeded_client)
    first = await seeded_client.post("/api/v1/placement/start", headers=headers)
    second = await seeded_client.post("/api/v1/placement/start", headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["session_id"] != second.json()["session_id"]

    factory = plan_factory
    async with factory() as db:
        old = await db.get(PracticeSession, uuid.UUID(first.json()["session_id"]))
        assert old.status == "abandoned"


async def test_placement_start_after_completion_rejected(seeded_client, plan_factory):
    headers = await _register(seeded_client)

    factory = plan_factory
    # 直接把用户标记成已测评（等价于评分钩子写完的终态）
    from sqlalchemy import update

    async with factory() as db:
        await db.execute(update(User).values(placement_at=datetime.now(timezone.utc)))
        await db.commit()

    resp = await seeded_client.post("/api/v1/placement/start", headers=headers)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# 报告完成钩子：placement_at + 路径重排
# ---------------------------------------------------------------------------

async def _make_placement_report_done(session_id, factory, overall=6.0):
    """模拟一次已完成评分的测评会话。"""
    async with factory() as db:
        session = await db.get(PracticeSession, session_id)
        report = ScoreReport(
            session_id=session.id,
            user_id=session.user_id,
            status="completed",
            fluency=overall - 0.5,
            lexical=overall,
            grammar=overall + 0.5,
            pronunciation=overall - 1.0,
            overall_band=overall,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(report)
        session.status = "completed"
        session.ended_at = datetime.now(timezone.utc)
        await db.commit()
    return session_id


async def test_on_report_completed_marks_placement_and_generates_plan(seeded_client, plan_factory):
    headers = await _register(seeded_client)
    start = await seeded_client.post("/api/v1/placement/start", headers=headers)
    session_id = uuid.UUID(start.json()["session_id"])
    factory = plan_factory

    await _make_placement_report_done(session_id, factory)
    await recommender.on_report_completed(session_id)

    async with factory() as db:
        user = (await db.scalars(select(User))).first()
        assert user.placement_at is not None
        tasks = (
            await db.scalars(
                select(DailyTask).order_by(DailyTask.plan_date, DailyTask.sort)
            )
        ).all()
    # 未来 7 天每天至少 1 条（种子池很小，大题库下每天满 3 条）
    assert len(tasks) >= 7
    types = {t.task_type for t in tasks}
    assert "topic" in types and "corpus" in types


async def test_regenerate_is_idempotent_and_keeps_done(seeded_client, plan_factory):
    headers = await _register(seeded_client)
    start = await seeded_client.post("/api/v1/placement/start", headers=headers)
    session_id = uuid.UUID(start.json()["session_id"])
    await _make_placement_report_done(session_id, plan_factory)
    await recommender.on_report_completed(session_id)

    # 标记今天第一条为 done 后再触发重排：done 保留，其余 pending 被替换
    factory = plan_factory
    async with factory() as db:
        all_tasks = (await db.scalars(select(DailyTask))).all()
        first_today = sorted(
            (t for t in all_tasks if t.plan_date <= date.today()),
            key=lambda t: (t.plan_date, t.sort),
        )[0]
        done_id = first_today.id
        first_today.status = "done"
        await db.commit()

    created = await recommender.regenerate_future_tasks((await _get_user_id(factory)))
    assert created >= 0
    async with factory() as db:
        kept = await db.get(DailyTask, done_id)
        assert kept is not None and kept.status == "done"


async def _get_user_id(factory):
    async with factory() as db:
        user = (await db.scalars(select(User))).first()
        return user.id


# ---------------------------------------------------------------------------
# Dashboard 聚合
# ---------------------------------------------------------------------------

async def test_overview_needs_placement_for_new_user(seeded_client, plan_factory):
    headers = await _register(seeded_client)
    resp = await seeded_client.get("/api/v1/dashboard/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["needs_placement"] is True
    assert data["radar"] is None
    assert data["hero"]["predicted"]["band"] is None


async def test_overview_stats_with_history(seeded_client, plan_factory):
    headers = await _register(seeded_client, email="history@example.com")

    factory = plan_factory
    now = datetime.now(timezone.utc)
    async with factory() as db:
        user = (await db.scalars(select(User))).first()
        for i in range(5):
            started = now - timedelta(days=(4 - i))
            session = PracticeSession(
                user_id=user.id,
                mode="practice",
                part=1,
                status="completed",
                started_at=started,
                ended_at=started + timedelta(minutes=10),
            )
            db.add(session)
            await db.flush()
            score = 5.0 + i * 0.5
            db.add(
                ScoreReport(
                    session_id=session.id,
                    user_id=user.id,
                    status="completed",
                    fluency=score,
                    lexical=score,
                    grammar=score + 0.5,
                    pronunciation=score - 0.5,
                    overall_band=score,
                    completed_at=started,
                )
            )
        await db.commit()

    resp = await seeded_client.get("/api/v1/dashboard/overview", headers=headers)
    data = resp.json()
    assert data["needs_placement"] is False  # 有历史报告的老用户不强制补测评
    assert data["hero"]["predicted"]["band"] is not None  # 满 5 次可预测
    assert data["radar"] is not None
    assert len(data["trend_points"]) == 5
    assert data["hero"]["streak_days"] >= 1


async def test_weakness_endpoint_ranks_and_suggests(seeded_client, plan_factory):
    headers = await _register(seeded_client, email="weak@example.com")
    factory = plan_factory
    async with factory() as db:
        user = (await db.scalars(select(User))).first()
        session = PracticeSession(user_id=user.id, mode="practice", part=1, status="completed")
        db.add(session)
        await db.flush()
        db.add(
            ScoreReport(
                session_id=session.id,
                user_id=user.id,
                status="completed",
                fluency=7.0,
                lexical=7.0,
                grammar=7.0,
                pronunciation=5.0,  # 发音最弱
                overall_band=6.5,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    resp = await seeded_client.get("/api/v1/dashboard/weakness", headers=headers)
    data = resp.json()
    assert data["primary_dimension"] == "pronunciation"
    assert data["suggestions"], "应返回推荐话题"
