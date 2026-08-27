"""初始能力测评题池：固定白名单选题，覆盖面稳定可控（Part E M2）。

策略：按 name_en 白名单挑 5 道必考 P1 题（家乡/工作学习/住所/居住区域/
旅行，覆盖个人背景四大经典考察面）；题库缺题时自动用其他 must 话题的
P1 题补足——导入完整 145 话题题库后不会触发补位。
"""

import logging

from sqlalchemy import select

from app.db.models import Question, Topic

logger = logging.getLogger(__name__)

PLACEMENT_QUESTION_COUNT = 5

# 白名单：name_en → 话题定位说明（也用于日志排查）
PLACEMENT_TOPIC_NAMES = (
    "Hometown",
    "Work & Study",
    "Home & Accommodation",
    "The area you live in",
    "Travelling",
)


async def pick_placement_questions(db) -> list[Question]:
    """返回测评用 P1 题清单（每话题取 sort 最小的一题）。"""
    picked: list[Question] = []
    used_topic_ids: set = set()

    for name in PLACEMENT_TOPIC_NAMES:
        topic = await db.scalar(select(Topic).where(Topic.name_en == name))
        if topic is None:
            logger.warning("测评白名单话题缺失：%s", name)
            continue
        question = await db.scalar(
            select(Question)
            .where(Question.topic_id == topic.id, Question.part == 1)
            .order_by(Question.sort)
            .limit(1)
        )
        if question is None:
            logger.warning("话题 %s 缺少 P1 题", name)
            continue
        picked.append(question)
        used_topic_ids.add(topic.id)

    # 补位：白名单缺题时用其余 must 话题的 P1 题凑满
    if len(picked) < PLACEMENT_QUESTION_COUNT:
        fillers = (
            await db.scalars(
                select(Question)
                .join(Topic, Question.topic_id == Topic.id)
                .where(Question.part == 1, Topic.tag == "must")
                .order_by(Topic.created_at, Question.sort)
                .limit(50)
            )
        ).all()
        for q in fillers:
            if len(picked) >= PLACEMENT_QUESTION_COUNT:
                break
            if q.topic_id in used_topic_ids:
                continue
            picked.append(q)
            used_topic_ids.add(q.topic_id)

    return picked[:PLACEMENT_QUESTION_COUNT]
