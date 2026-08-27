"""Part D 知识库：topics 搜索/筛选/分页、详情聚合、词汇本 CRUD、导入幂等与种子合并。"""

import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.db.models import Expression, Question, SampleAnswer, Topic, TopicLink, UserVocabWord

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from import_topics import import_linked, import_p1, import_p2p3  # noqa: E402


async def _mk_topic(db, name_en, name_zh=None, category=None, tag=None, questions=(1,)):
    topic = Topic(name_en=name_en, name_zh=name_zh, category=category, tag=tag)
    db.add(topic)
    await db.flush()
    for part in questions:
        db.add(Question(topic_id=topic.id, part=part, content_en=f"Q {name_en} part{part}", sort=0))
    await db.commit()
    return topic


# ---------------------------------------------------------------- 列表 API

@pytest.mark.asyncio
async def test_topics_search_filter_pagination(client, auth_headers, db_session):
    await _mk_topic(db_session, "Hometown", "家乡", category=None, tag="must", questions=(1,))
    await _mk_topic(db_session, "Music", "音乐", category=None, tag="new", questions=(1,))
    await _mk_topic(db_session, "A Childhood Friend", "发小", category="person", tag="new", questions=(2,))
    await _mk_topic(db_session, "Getting Lost", "迷路", category="place", tag="retained", questions=(2,))

    # 基础分页结构
    resp = await client.get("/api/v1/topics?part=1", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2 and body["page"] == 1 and len(body["items"]) == 2

    # 搜索（中文/英文）
    zh = await client.get("/api/v1/topics?part=2&search=发小", headers=auth_headers)
    assert zh.json()["total"] == 1 and zh.json()["items"][0]["name_en"] == "A Childhood Friend"
    en = await client.get("/api/v1/topics?part=1&search=home", headers=auth_headers)
    assert en.json()["total"] == 1 and en.json()["items"][0]["name_en"] == "Hometown"

    # 分类与标签
    cat = await client.get("/api/v1/topics?part=2&category=place", headers=auth_headers)
    assert cat.json()["total"] == 1 and cat.json()["items"][0]["name_en"] == "Getting Lost"
    tag = await client.get("/api/v1/topics?part=2&tag=new", headers=auth_headers)
    assert tag.json()["total"] == 1

    # 分页：page_size=1
    pg = await client.get("/api/v1/topics?part=1&page_size=1&page=1", headers=auth_headers)
    assert len(pg.json()["items"]) == 1 and pg.json()["total"] == 2


@pytest.mark.asyncio
async def test_topic_detail_aggregation(client, auth_headers, db_session):
    topic = await _mk_topic(db_session, "A Childhood Friend", "发小", category="person", tag="new", questions=(2, 3))
    q2 = (await db_session.scalars(select(Question).where(Question.topic_id == topic.id, Question.part == 2))).first()
    db_session.add(SampleAnswer(topic_id=topic.id, question_id=None, part=2, text_en="Sample text.",
                                summary_zh="中文概要", source="p2p3"))
    db_session.add(SampleAnswer(topic_id=topic.id, question_id=q2.id, part=2, text_en="q answer", source="p2p3"))
    db_session.add(Expression(topic_id=topic.id, text_en="get the hang of", meaning_zh="掌握"))
    await db_session.commit()

    # 串联组：另一个话题共享本话题的范文
    other = await _mk_topic(db_session, "A Kind Person", "好人", questions=(2,))
    shared = SampleAnswer(topic_id=topic.id, question_id=None, part=2, text_en="Linked sample", source="linked")
    db_session.add(shared)
    await db_session.flush()
    db_session.add(TopicLink(group_name="发小 + 好人", shared_answer_id=shared.id, topic_id=topic.id))
    db_session.add(TopicLink(group_name="发小 + 好人", shared_answer_id=shared.id, topic_id=other.id))
    await db_session.commit()

    resp = await client.get(f"/api/v1/topics/{topic.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["questions"]) == 2
    q2_item = next(q for q in body["questions"] if q["part"] == 2)
    assert q2_item["sample_answer"]["text_en"] == "q answer"
    assert any(a["source"] == "p2p3" and a["summary_zh"] == "中文概要" for a in body["sample_answers"])
    assert body["expressions"][0]["text_en"] == "get the hang of"
    assert len(body["links"]) == 1
    assert set(body["links"][0]["linked_topic_names"]) == {"发小", "好人"}


# ---------------------------------------------------------------- 词汇本 CRUD

@pytest.mark.asyncio
async def test_vocab_crud(client, auth_headers, db_session):
    topic = await _mk_topic(db_session, "Hometown", "家乡")

    # 新增
    resp = await client.post("/api/v1/vocab-words", headers=auth_headers, json={
        "word": "get the hang of", "context_en": "He got the hang of it.", "source_topic_id": str(topic.id),
    })
    assert resp.status_code == 200
    word = resp.json()
    assert word["source_topic_name"] == "家乡"
    word_id = word["id"]

    # 重复添加幂等（同 id，不报错）
    resp2 = await client.post("/api/v1/vocab-words", headers=auth_headers, json={"word": "get the hang of"})
    assert resp2.status_code == 200 and resp2.json()["id"] == word_id

    # 列表 + 搜索 + 收藏筛选
    lst = await client.get("/api/v1/vocab-words", headers=auth_headers)
    assert lst.json()["total"] == 1
    assert (await client.get("/api/v1/vocab-words?search=hang", headers=auth_headers)).json()["total"] == 1
    assert (await client.get("/api/v1/vocab-words?search=nope", headers=auth_headers)).json()["total"] == 0

    # 收藏切换
    fav = await client.patch(f"/api/v1/vocab-words/{word_id}/favorite", headers=auth_headers)
    assert fav.json()["is_favorite"] is True
    assert (await client.get("/api/v1/vocab-words?favorite=true", headers=auth_headers)).json()["total"] == 1
    fav2 = await client.patch(f"/api/v1/vocab-words/{word_id}/favorite", headers=auth_headers)
    assert fav2.json()["is_favorite"] is False

    # 删除
    assert (await client.delete(f"/api/v1/vocab-words/{word_id}", headers=auth_headers)).status_code == 200
    assert (await client.get("/api/v1/vocab-words", headers=auth_headers)).json()["total"] == 0
    assert (await client.delete(f"/api/v1/vocab-words/{word_id}", headers=auth_headers)).status_code == 404


# ---------------------------------------------------------------- 导入幂等与种子合并

MINI_P1 = {"topics": [{
    "name_en": "Home/Accommodation", "name_zh": "住所", "tag": "must", "note": "",
    "questions": [
        {"no": 1, "question": "Do you live in a house?", "answer": "I live in an apartment."},
        {"no": 2, "question": "What is your home like?", "answer": "It is cozy."},
    ],
}]}

MINI_P2P3 = {"topics": [{
    "name_zh": "发小", "name_en": "A Childhood Friend", "tag": "new", "category": "person", "note": "",
    "cue_prompt": "Describe a friend from your childhood",
    "you_should_say": ["Who he/she is"],
    "summary_zh": "童年好友",
    "sample_en": "Peter was my guitar tutor.",
    "p3_questions": [{"no": 1, "question": "Is friendship important?", "answer": "Yes."}],
}]}

MINI_LINKED = {"groups": [{
    "group_name": "发小 + 好人", "tag": "new",
    "summary_zh": "概要", "sample_en": "Shared sample text.",
    "matched": [{"alias": "发小", "name_zh": "发小"}, {"alias": "不存在的话题", "name_zh": None}],
}]}


@pytest.mark.asyncio
async def test_import_idempotent_and_seed_merge(db_session):
    # 预置种子话题（SEED_ALIAS 目标）+ 旧题目，验证导入后合并而非重复
    seed = Topic(name_en="Home & Accommodation", name_zh="家与住所", category="home", tag="must")
    db_session.add(seed)
    await db_session.flush()
    db_session.add(Question(topic_id=seed.id, part=1, content_en="旧种子问题", sort=0))
    await db_session.commit()
    seed_id = seed.id

    for _ in range(2):  # 跑两遍验证幂等
        await import_p1(db_session, MINI_P1)
        await import_p2p3(db_session, MINI_P2P3)
        await import_linked(db_session, MINI_LINKED, MINI_P2P3)
        await db_session.commit()

    # 话题：种子话题被复用（别名映射），PDF 新话题各 1 个，无重复
    topics = (await db_scalars_all(db_session, select(Topic)))
    assert len(topics) == 2
    merged = next(t for t in topics if t.id == seed_id)
    assert merged.name_en == "Home & Accommodation"
    assert merged.name_zh == "住所"  # PDF 数据覆盖字段

    # 种子旧问题被 PDF 题目替换
    qs = (await db_scalars_all(db_session, select(Question).where(Question.topic_id == seed_id)))
    assert sorted(q.content_en for q in qs) == ["Do you live in a house?", "What is your home like?"]

    # 题目级范文挂在问题上
    answers = (await db_scalars_all(db_session, select(SampleAnswer)))
    assert len(answers) == 5  # p1 两题 + p2p3 topic级 + p3 一题 + linked 一篇
    p2_topic_answer = [a for a in answers if a.source == "p2p3" and a.question_id is None]
    assert p2_topic_answer and p2_topic_answer[0].summary_zh == "童年好友"

    # 串联：只匹配到 1 个有效话题（"不存在的话题" 被跳过）
    links = (await db_scalars_all(db_session, select(TopicLink)))
    assert len(links) == 1
    assert links[0].topic_id == next(t for t in topics if t.name_en == "A Childhood Friend").id


async def db_scalars_all(db, stmt):
    return (await db.scalars(stmt)).all()


@pytest.mark.asyncio
async def test_import_run_twice_counts_identical(db_session):
    """独立验证：两轮完整导入后各表计数一致。"""
    async def counts():
        return (
            (await db_session.scalar(select(func.count(Topic.id)))),
            (await db_session.scalar(select(func.count(Question.id)))),
            (await db_session.scalar(select(func.count(SampleAnswer.id)))),
            (await db_session.scalar(select(func.count(TopicLink.id)))),
        )

    await import_p1(db_session, MINI_P1)
    await import_p2p3(db_session, MINI_P2P3)
    await import_linked(db_session, MINI_LINKED, MINI_P2P3)
    await db_session.commit()
    first = await counts()

    await import_p1(db_session, MINI_P1)
    await import_p2p3(db_session, MINI_P2P3)
    await import_linked(db_session, MINI_LINKED, MINI_P2P3)
    await db_session.commit()
    second = await counts()

    assert first == second
    assert first[0] == 2  # 两个话题
