"""话题题库接口：浏览（搜索/分类/标签/分页）、详情（题目+范文+表达+串联）、范文跟读。"""

import struct

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import Expression, Question, SampleAnswer, Topic, TopicLink, User
from app.schemas.topic import (
    ExpressionOut,
    QuestionWithAnswerOut,
    SampleAnswerOut,
    TopicDetailOut,
    TopicLinkOut,
    TopicListOut,
    TopicOut,
)

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1200)
    voice_key: str = "en_female_anna"
    speed_key: str = "normal"


def _pcm_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    """24kHz/16bit/单声道 PCM 加 WAV 头，前端 <audio> 可直接播放。"""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, 1,
        sample_rate, sample_rate * 2, 2, 16, b"data", len(pcm),
    )
    return header + pcm


@router.post("/speak")
async def speak_text(
    payload: SpeakRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.services.volcengine.speech import synthesize_tts_stream

    pcm = await synthesize_tts_stream(
        payload.text, user, db,
        voice_key=payload.voice_key, speed_key=payload.speed_key,
    )
    return Response(content=_pcm_to_wav(pcm), media_type="audio/wav")


@router.get("", response_model=TopicListOut)
async def list_topics(
    part: int = Query(default=1, ge=1, le=3),
    category: str | None = None,
    tag: str | None = Query(default=None, description="new / retained / must"),
    search: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TopicListOut:
    # 有该 part 题目的话题才出现在对应 tab（Part2/3 共用 part=2 计数）
    count_part = 1 if part == 1 else 2
    count_sq = (
        select(Question.topic_id, func.count().label("cnt"))
        .where(Question.part == count_part)
        .group_by(Question.topic_id)
        .subquery()
    )
    stmt = (
        select(Topic, func.coalesce(count_sq.c.cnt, 0))
        .outerjoin(count_sq, count_sq.c.topic_id == Topic.id)
        .where(count_sq.c.cnt > 0)
        .order_by(Topic.created_at)
    )
    if category:
        stmt = stmt.where(Topic.category == category)
    if tag:
        stmt = stmt.where(Topic.tag == tag)
    if search:
        kw = f"%{search.strip()}%"
        stmt = stmt.where(or_(Topic.name_en.ilike(kw), Topic.name_zh.ilike(kw)))

    total = (
        await db.scalar(select(func.count()).select_from(stmt.subquery()))
    ) or 0
    rows = (
        await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
    ).all()
    return TopicListOut(
        items=[
            TopicOut(
                id=topic.id,
                name_en=topic.name_en,
                name_zh=topic.name_zh,
                category=topic.category,
                tag=topic.tag,
                question_count=int(cnt),
            )
            for topic, cnt in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/expressions", response_model=list[ExpressionOut])
async def list_expressions(
    topic_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExpressionOut]:
    stmt = select(Expression).order_by(Expression.created_at.desc())
    if topic_id:
        try:
            import uuid as uuid_mod

            stmt = stmt.where(Expression.topic_id == uuid_mod.UUID(topic_id))
        except ValueError:
            return []
    rows = (await db.scalars(stmt.offset((page - 1) * page_size).limit(page_size))).all()
    return [ExpressionOut.model_validate(e) for e in rows]


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
            select(Question).where(Question.topic_id == topic.id).order_by(Question.part, Question.sort)
        )
    ).all()
    # 题目级范文（P1 每题答案 / P3 追问答案）
    q_answers = {
        a.question_id: a
        for a in (
            await db.scalars(
                select(SampleAnswer).where(
                    SampleAnswer.topic_id == topic.id, SampleAnswer.question_id.isnot(None)
                )
            )
        ).all()
    }
    # topic 级范文（P2 主范文 + linked 串联范文）
    topic_answers = (
        await db.scalars(
            select(SampleAnswer)
            .where(SampleAnswer.topic_id == topic.id, SampleAnswer.question_id.is_(None))
            .order_by(SampleAnswer.source)
        )
    ).all()
    expressions = (
        await db.scalars(
            select(Expression).where(Expression.topic_id == topic.id).order_by(Expression.created_at)
        )
    ).all()

    # 串联：本话题所在的组 → 组内其他话题名 + 共享范文
    links: list[TopicLinkOut] = []
    link_rows = (
        await db.scalars(select(TopicLink).where(TopicLink.topic_id == topic.id))
    ).all()
    for link in link_rows:
        group_rows = (
            await db.scalars(
                select(TopicLink).where(TopicLink.group_name == link.group_name)
            )
        ).all()
        names = [
            t.name_zh or t.name_en
            for t in (
                await db.scalars(
                    select(Topic).where(Topic.id.in_([g.topic_id for g in group_rows]))
                )
            ).all()
        ]
        shared = await db.get(SampleAnswer, link.shared_answer_id)
        if shared is not None:
            links.append(
                TopicLinkOut(
                    group_name=link.group_name,
                    linked_topic_names=names,
                    shared_answer=SampleAnswerOut.model_validate(shared),
                )
            )

    return TopicDetailOut(
        id=topic.id,
        name_en=topic.name_en,
        name_zh=topic.name_zh,
        category=topic.category,
        tag=topic.tag,
        question_count=len(questions),
        questions=[
            QuestionWithAnswerOut(
                id=q.id,
                part=q.part,
                content_en=q.content_en,
                cue_card=q.cue_card,
                sort=q.sort,
                sample_answer=(
                    SampleAnswerOut.model_validate(q_answers[q.id])
                    if q.id in q_answers
                    else None
                ),
            )
            for q in questions
        ],
        sample_answers=[SampleAnswerOut.model_validate(a) for a in topic_answers],
        expressions=[ExpressionOut.model_validate(e) for e in expressions],
        links=links,
    )
