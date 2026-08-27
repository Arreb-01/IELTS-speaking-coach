# -*- coding: utf-8 -*-
"""中间 JSON → 数据库导入（Part D M3）。

用法：
  python scripts/import_topics.py                     # 导入 + 生成表达库（LLM，断点续跑）
  python scripts/import_topics.py --skip-expressions  # 只导结构数据（不联网）
  python scripts/import_topics.py --prune             # 额外删除种子独有且无练习记录的话题

幂等：按 name_en upsert 话题（PDF 别名优先映射到种子名，保住练习历史外键），
题目/范文/表达/串联对已存在的话题删除重建；种子独有话题默认保留。
表达库断点续跑：已有表达的话题跳过 LLM 调用。
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import delete, func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/（复用 parse_pdf 的 LLM 封装）

from app.db.base import async_session_factory  # noqa: E402
from app.db.models import (  # noqa: E402
    Expression,
    PracticeSession,
    Question,
    SampleAnswer,
    Topic,
    TopicLink,
)

logger = logging.getLogger("import_topics")
PARSED = Path(__file__).resolve().parent / "parsed"

# PDF 话题名 → 种子 name_en（合并到已有话题行，保住 practice_sessions.topic_id）
SEED_ALIAS = {
    "Home/Accommodation": "Home & Accommodation",
    "Work or study": "Work & Study",
    "An Old Family Item": "An Old Object in Your Family",
}


async def upsert_topic(db, *, name_en: str, name_zh: str, tag: str, category: str | None) -> Topic:
    topic = await db.scalar(select(Topic).where(Topic.name_en == name_en))
    if topic is None:
        topic = Topic(name_en=name_en)
        db.add(topic)
    topic.name_zh = name_zh or topic.name_zh
    topic.tag = tag or topic.tag
    if category:  # P1 无分类时保留种子/已有值
        topic.category = category
    await db.flush()
    return topic


async def clear_topic_content(db, topic: Topic, parts: list[int]) -> None:
    """删除话题在指定 part 的题目、题目级范文与表达（PDF 数据为权威，重建）。"""
    await db.execute(
        delete(SampleAnswer).where(
            SampleAnswer.topic_id == topic.id, SampleAnswer.question_id.isnot(None)
        )
    )
    await db.execute(delete(Question).where(Question.topic_id == topic.id, Question.part.in_(parts)))


async def import_p1(db, data: dict) -> dict:
    topics = questions = answers = 0
    for t in data["topics"]:
        if not t["name_en"]:
            continue
        name_en = SEED_ALIAS.get(t["name_en"], t["name_en"])
        topic = await upsert_topic(db, name_en=name_en, name_zh=t.get("name_zh", ""),
                                   tag=t["tag"], category=None)
        await clear_topic_content(db, topic, [1])
        for i, q in enumerate(t["questions"]):
            question = Question(topic_id=topic.id, part=1, content_en=q["question"], sort=i)
            db.add(question)
            await db.flush()
            questions += 1
            if q["answer"]:
                db.add(SampleAnswer(topic_id=topic.id, question_id=question.id, part=1,
                                    text_en=q["answer"], source="p1"))
                answers += 1
        topics += 1
    return {"p1_topics": topics, "p1_questions": questions, "p1_answers": answers}


async def import_p2p3(db, data: dict) -> dict:
    topics = questions = topic_answers = q_answers = 0
    for t in data["topics"]:
        if not t["name_en"] or not t["name_zh"]:
            continue
        topic = await upsert_topic(db, name_en=t["name_en"], name_zh=t["name_zh"],
                                   tag=t["tag"], category=t["category"] or None)
        await clear_topic_content(db, topic, [2, 3])
        await db.execute(delete(SampleAnswer).where(
            SampleAnswer.topic_id == topic.id, SampleAnswer.source == "p2p3"))

        # Part 2：单题，Cue Card 存 JSONB
        cue = {
            "prompt": t["cue_prompt"],
            "you_should_say": t["you_should_say"],
            "summary_zh": t["summary_zh"],
        }
        db.add(Question(topic_id=topic.id, part=2, content_en=t["cue_prompt"], cue_card=cue, sort=0))
        questions += 1
        # Part 2 范文挂 topic 级
        if t["sample_en"]:
            db.add(SampleAnswer(topic_id=topic.id, question_id=None, part=2,
                                text_en=t["sample_en"], summary_zh=t["summary_zh"], source="p2p3"))
            topic_answers += 1
        # Part 3：问题 + 答案挂 question 级
        for i, q in enumerate(t["p3_questions"]):
            question = Question(topic_id=topic.id, part=3, content_en=q["question"], sort=i)
            db.add(question)
            await db.flush()
            questions += 1
            if q["answer"]:
                db.add(SampleAnswer(topic_id=topic.id, question_id=question.id, part=3,
                                    text_en=q["answer"], source="p2p3"))
                q_answers += 1
        topics += 1
    return {"p2p3_topics": topics, "p2p3_questions": questions,
            "p2p3_topic_answers": topic_answers, "p2p3_q_answers": q_answers}


async def import_linked(db, data: dict, p2p3: dict) -> dict:
    # 中文名 → topic 行（PDF 话题刚导入，name_zh 已是 PDF 中文名）
    zh_rows = {
        t.name_zh: t
        for t in (await db.scalars(select(Topic))).all()
        if t.name_zh
    }
    # 全删重建（linked 数据完全来自 JSON）
    await db.execute(delete(TopicLink))
    await db.execute(delete(SampleAnswer).where(SampleAnswer.source == "linked"))

    groups = links = skipped = 0
    for g in data["groups"]:
        matched = [m["name_zh"] for m in g["matched"] if m["name_zh"] and m["name_zh"] in zh_rows]
        unmatched = [m["alias"] for m in g["matched"] if not m["name_zh"] or m["name_zh"] not in zh_rows]
        skipped += len(unmatched)
        if not matched or not g["sample_en"]:
            continue
        anchor = zh_rows[matched[0]]
        shared = SampleAnswer(topic_id=anchor.id, question_id=None, part=2,
                              text_en=g["sample_en"], summary_zh=g["summary_zh"], source="linked")
        db.add(shared)
        await db.flush()
        for name_zh in matched:
            db.add(TopicLink(group_name=g["group_name"], shared_answer_id=shared.id,
                             topic_id=zh_rows[name_zh].id))
            links += 1
        groups += 1
    return {"linked_groups": groups, "linked_links": links, "linked_unmatched_aliases": skipped}


# ---------------------------------------------------------------- 表达库

EXPR_SYSTEM = (
    "你是雅思口语教研编辑。从范文中提取 5-8 个高分表达（短语/搭配/习语，"
    "不要单个简单词），每个给中文释义和范文中的原句例句。"
    '仅输出 JSON {"expressions": [{"text_en": "...", "meaning_zh": "...", "example_en": "..."}]}'
)


async def gen_expressions(db, p1: dict, p2p3: dict, linked: dict, force: bool) -> dict:
    from app.services.volcengine import ark

    from parse_pdf import ask_llm_json  # 复用 Key 解析与调用封装

    # 话题 → 送 LLM 的范文素材
    materials: dict[str, str] = {}  # name_en -> text
    for t in p1["topics"]:
        if t["name_en"] and t["questions"]:
            texts = [q["answer"] for q in t["questions"] if q["answer"]][:2]
            if texts:
                materials[SEED_ALIAS.get(t["name_en"], t["name_en"])] = "\n\n".join(texts)
    for t in p2p3["topics"]:
        if t["name_en"] and t["sample_en"]:
            materials[t["name_en"]] = t["sample_en"]

    existing = {
        tid for (tid,) in (await db.execute(select(Expression.topic_id).distinct())).all()
    }
    name_to_topic = {t.name_en: t for t in (await db.scalars(select(Topic))).all()}
    generated = skipped = failed = 0
    for name_en, text in materials.items():
        topic = name_to_topic.get(name_en)
        if topic is None:
            continue
        if topic.id in existing and not force:
            skipped += 1
            continue
        await db.execute(delete(Expression).where(Expression.topic_id == topic.id))
        data = await ask_llm_json(EXPR_SYSTEM, f"话题：{topic.name_zh or name_en}\n\n{text}", max_tokens=2000)
        items = data.get("expressions") if isinstance(data, dict) else None
        if not isinstance(items, list):
            logger.warning("表达提取失败：%s", name_en)
            failed += 1
            continue
        for item in items[:8]:
            if not isinstance(item, dict) or not item.get("text_en") or not item.get("meaning_zh"):
                continue
            db.add(Expression(
                topic_id=topic.id,
                text_en=str(item["text_en"])[:500],
                meaning_zh=str(item["meaning_zh"])[:500],
                example_en=str(item.get("example_en", ""))[:2000] or None,
            ))
        generated += 1
        await db.flush()
        logger.info("expressions %d/%d: %s", generated + skipped, len(materials), name_en)
    return {"expr_generated": generated, "expr_skipped": skipped, "expr_failed": failed}


async def prune_orphan_topics(db) -> int:
    """删除种子独有（无 PDF 来源内容）且从未被练习引用的话题。"""
    used = {
        tid for (tid,) in (await db.execute(select(PracticeSession.topic_id).distinct())).all()
    }
    pdf_topics = {
        SEED_ALIAS.get(t["name_en"], t["name_en"])
        for data_key in ("p1", "p2p3")
        for t in json.loads((PARSED / f"{data_key}.json").read_text(encoding="utf-8"))["topics"]
        if t["name_en"]
    }
    removed = 0
    for topic in (await db.scalars(select(Topic))).all():
        if topic.name_en not in pdf_topics and topic.id not in used:
            await db.delete(topic)
            removed += 1
    return removed


async def main(skip_expressions: bool, prune: bool) -> None:
    p1 = json.loads((PARSED / "p1.json").read_text(encoding="utf-8"))
    p2p3 = json.loads((PARSED / "p2p3.json").read_text(encoding="utf-8"))
    linked = json.loads((PARSED / "linked.json").read_text(encoding="utf-8"))

    stats: dict = {}
    async with async_session_factory() as db:
        stats.update(await import_p1(db, p1))
        stats.update(await import_p2p3(db, p2p3))
        stats.update(await import_linked(db, linked, p2p3))
        if not skip_expressions:
            stats.update(await gen_expressions(db, p1, p2p3, linked, force=False))
        if prune:
            stats["pruned_topics"] = await prune_orphan_topics(db)
        total = {
            "topics": (await db.scalar(select(func.count(Topic.id)))),
            "questions": (await db.scalar(select(func.count(Question.id)))),
            "sample_answers": (await db.scalar(select(func.count(SampleAnswer.id)))),
            "expressions": (await db.scalar(select(func.count(Expression.id)))),
            "topic_links": (await db.scalar(select(func.count(TopicLink.id)))),
        }
        await db.commit()

    print(json.dumps({**stats, "db_total": total}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-expressions", action="store_true", help="跳过表达库 LLM 生成")
    ap.add_argument("--prune", action="store_true", help="删除无练习记录的种子独有话题")
    args = ap.parse_args()
    asyncio.run(main(args.skip_expressions, args.prune))
