"""练习会话 REST：创建（签发 WS ticket）/ 详情 / 音频回放。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import PracticeSession, PracticeTurn, Topic, User
from app.schemas.topic import (
    PracticeCreateRequest,
    PracticeCreateResponse,
    PracticeSessionDetailOut,
    PracticeSessionOut,
    PracticeTurnOut,
    TopicOut,
)
from app.services.practice_engine import registry
from app.services.storage import open_audio_file

router = APIRouter()


@router.post("", response_model=PracticeCreateResponse, status_code=201)
async def create_practice(
    body: PracticeCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PracticeCreateResponse:
    if body.accent not in ("en_female_anna", "en_female_ariana", "en_male_jackson"):
        raise HTTPException(422, "不支持的音色")
    if body.speed not in ("slow", "normal", "fast"):
        raise HTTPException(422, "不支持的语速")
    if body.mode not in ("practice", "mock"):
        raise HTTPException(422, "不支持的会话模式")

    topic = await db.get(Topic, body.topic_id)
    if topic is None:
        raise HTTPException(404, "话题不存在")

    # 单活动会话：放弃该用户其他未完成会话
    other_active = await db.scalars(
        select(PracticeSession).where(
            PracticeSession.user_id == user.id,
            PracticeSession.status == "in_progress",
        )
    )
    for stale in other_active:
        stale.status = "abandoned"

    session = PracticeSession(
        user_id=user.id,
        mode=body.mode,
        part=body.part,
        topic_id=topic.id,
        accent=body.accent,
        speed=body.speed,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    ticket = await registry.issue_ticket(session.id)
    return PracticeCreateResponse(
        session_id=session.id,
        ws_ticket=ticket,
        ws_path=f"/api/v1/ws/practice/{session.id}?ticket={ticket}",
    )


@router.get("", response_model=list[PracticeSessionOut])
async def list_practices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PracticeSessionOut]:
    sessions = await db.scalars(
        select(PracticeSession)
        .where(PracticeSession.user_id == user.id)
        .order_by(PracticeSession.started_at.desc())
        .limit(20)
    )
    return [PracticeSessionOut.model_validate(s) for s in sessions]


@router.get("/{session_id}", response_model=PracticeSessionDetailOut)
async def get_practice(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PracticeSessionDetailOut:
    session = await db.get(PracticeSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "练习记录不存在")

    topic = await db.get(Topic, session.topic_id) if session.topic_id else None
    turns = (
        await db.scalars(
            select(PracticeTurn)
            .where(PracticeTurn.session_id == session.id)
            .order_by(PracticeTurn.seq)
        )
    ).all()
    return PracticeSessionDetailOut(
        **PracticeSessionOut.model_validate(session).model_dump(),
        topic=TopicOut.model_validate(topic) if topic else None,
        turns=[
            PracticeTurnOut(
                id=t.id,
                seq=t.seq,
                question_text=t.question_text,
                is_followup=t.is_followup,
                user_transcript=t.user_transcript,
                has_audio=bool(t.audio_path),
                started_at=t.started_at,
                ended_at=t.ended_at,
            )
            for t in turns
        ],
    )


@router.get("/{session_id}/turns/{turn_id}/audio")
async def get_turn_audio(
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    turn = await db.get(PracticeTurn, turn_id)
    if turn is None or turn.session_id != session_id:
        raise HTTPException(404, "录音不存在")
    session = await db.get(PracticeSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(404, "录音不存在")
    if not turn.audio_path:
        raise HTTPException(404, "该轮次没有录音")

    file = open_audio_file(turn.audio_path)
    if file is None:
        raise HTTPException(404, "录音文件缺失")
    return StreamingResponse(file, media_type="audio/wav")
