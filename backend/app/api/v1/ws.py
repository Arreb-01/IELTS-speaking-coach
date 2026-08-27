"""练习 WebSocket 端点：ticket 鉴权 → 创建或重连引擎。"""

import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.db.base import async_session_factory
from app.db.models import PracticeSession, Question, Topic, User
from app.services.practice_engine import registry
from app.services.practice_engine.engine import PracticeEngine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/practice/{session_id}")
async def practice_websocket(websocket: WebSocket, session_id: uuid.UUID) -> None:
    ticket = websocket.query_params.get("ticket", "")
    resolved_session_id = await registry.consume_ticket(ticket)
    if resolved_session_id is None or resolved_session_id != session_id:
        await websocket.close(code=4401, reason="ticket 无效或已过期")
        return

    async with async_session_factory() as db:
        session = await db.get(PracticeSession, session_id)
        if session is None:
            await websocket.close(code=4404, reason="练习会话不存在")
            return
        if session.status != "in_progress":
            await websocket.close(code=4410, reason="会话已结束")
            return
        user = await db.get(User, session.user_id)
        topic = await db.get(Topic, session.topic_id) if session.topic_id else None
        if topic is not None:
            # 普通练习：按话题取题
            questions = list(
                await db.scalars(
                    select(Question).where(Question.topic_id == topic.id).order_by(Question.sort)
                )
            )
        elif session.question_ids:
            # 能力测评：会话创建时已固定题目清单，按存储顺序还原
            wanted = [
                uuid.UUID(qid) if isinstance(qid, str) else qid for qid in session.question_ids
            ]
            rows = await db.scalars(select(Question).where(Question.id.in_(wanted)))
            by_id = {q.id: q for q in rows}
            questions = [by_id[qid] for qid in wanted if qid in by_id]
        else:
            questions = []

    await websocket.accept()

    # 断线重连：复用既有引擎
    engine = registry.get_engine(session_id)
    if engine is None:
        engine = PracticeEngine(
            user=user,
            session=session,
            topic=topic,
            questions=list(questions),
            p1_question_count=len(questions) if (topic is None and questions) else None,
        )
        registry.register(engine)

    try:
        await engine.run(websocket)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("练习引擎异常退出：%s", session_id)
        await engine._finish(abandon=True)
    finally:
        if engine._closed:
            registry.detach(session_id)
