"""初始能力测评 REST：创建 5 题简短问答会话（复用练习引擎）。

流程：POST /placement/start → 前端带 query.placement=1 进练习页 →
答题结束自动评分（管线零改动）→ 报告页设目标分 → Dashboard 领路径。
placement_at 由「报告完成钩子」写入（recommender.on_report_completed）。
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import PracticeSession, User
from app.schemas.progress import PlacementStartOut
from app.services.practice_engine import registry
from app.services.scoring.placement_pool import pick_placement_questions

router = APIRouter()


@router.post("/start", response_model=PlacementStartOut, status_code=201)
async def start_placement(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlacementStartOut:
    if user.placement_at is not None:
        raise HTTPException(409, "已完成能力测评，无需重复测评")

    questions = await pick_placement_questions(db)
    if len(questions) < 3:
        raise HTTPException(503, "题库尚未就绪，请联系管理员导入话题题库")

    # 单活动会话约束：放弃既有未完成会话（含未完成的旧测评）
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
        mode="practice",
        part=1,
        topic_id=None,  # 测评会话标识：topic 空 + question_ids 非空
        question_ids=[str(q.id) for q in questions],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    ticket = await registry.issue_ticket(session.id)
    return PlacementStartOut(
        session_id=session.id,
        ws_ticket=ticket,
        ws_path=f"/api/v1/ws/practice/{session.id}?ticket={ticket}",
        total_questions=len(questions),
    )
