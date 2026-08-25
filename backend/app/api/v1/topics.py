"""话题题库接口。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import Question, Topic, User
from app.schemas.topic import QuestionOut, TopicDetailOut, TopicOut

router = APIRouter()


@router.get("", response_model=list[TopicOut])
async def list_topics(
    part: int = Query(default=1, ge=1, le=3),
    category: str | None = None,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TopicOut]:
    count_sq = (
        select(Question.topic_id, func.count().label("cnt"))
        .where(Question.part == part)
        .group_by(Question.topic_id)
        .subquery()
    )
    stmt = (
        select(Topic, func.coalesce(count_sq.c.cnt, 0))
        .outerjoin(count_sq, count_sq.c.topic_id == Topic.id)
        .order_by(Topic.created_at)
    )
    if part == 1:
        # Part 1 话题：含 part=1 题目；Part2&3 话题按分类浏览
        stmt = stmt.where(count_sq.c.cnt > 0)
    else:
        # Part 2/3 浏览：含 part=2 Cue Card 的话题
        count_sq2 = (
            select(Question.topic_id, func.count().label("cnt"))
            .where(Question.part == 2)
            .group_by(Question.topic_id)
            .subquery()
        )
        stmt = (
            select(Topic, func.coalesce(count_sq2.c.cnt, 0))
            .outerjoin(count_sq2, count_sq2.c.topic_id == Topic.id)
            .where(count_sq2.c.cnt > 0)
            .order_by(Topic.created_at)
        )
    if category:
        stmt = stmt.where(Topic.category == category)

    rows = (await db.execute(stmt)).all()
    return [
        TopicOut(
            id=topic.id,
            name_en=topic.name_en,
            name_zh=topic.name_zh,
            category=topic.category,
            tag=topic.tag,
            question_count=int(cnt),
        )
        for topic, cnt in rows
    ]


@router.get("/{topic_id}", response_model=TopicDetailOut)
async def get_topic(
    topic_id: str,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TopicDetailOut:
    import uuid as uuid_mod

    try:
        topic_uuid = uuid_mod.UUID(topic_id)
    except ValueError:
        raise HTTPException(404, "话题不存在")

    topic = await db.get(Topic, topic_uuid)
    if topic is None:
        raise HTTPException(404, "话题不存在")
    questions = (
        await db.scalars(
            select(Question).where(Question.topic_id == topic.id).order_by(Question.sort)
        )
    ).all()
    return TopicDetailOut(
        id=topic.id,
        name_en=topic.name_en,
        name_zh=topic.name_zh,
        category=topic.category,
        tag=topic.tag,
        question_count=len(questions),
        questions=[QuestionOut.model_validate(q) for q in questions],
    )
