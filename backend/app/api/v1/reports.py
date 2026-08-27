"""评分报告 REST：报告详情 / 历史列表 / 提分趋势。

报告生成与轮询：练习结束后引擎自动触发评分（见 practice_engine），
前端轮询 GET /practices/{id}/report 直到 status=completed/failed。
"""

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import PracticeSession, ScoreReport, Topic, TurnAnalysis, User
from app.schemas.report import (
    ReportSessionBrief,
    ScoreReportDetailOut,
    ScoreReportListItemOut,
    TrendOut,
    TrendPoint,
    TurnAnalysisOut,
)
from app.services.scoring import engine as scoring_engine

router = APIRouter()


async def _load_report_context(
    db: AsyncSession, user: User, session_id
) -> tuple[ScoreReport, PracticeSession | None, Topic | None]:
    report = await db.scalar(
        select(ScoreReport).where(ScoreReport.session_id == session_id)
    )
    if report is None or report.user_id != user.id:
        raise HTTPException(404, "评分报告不存在")
    session = await db.get(PracticeSession, session_id)
    topic = await db.get(Topic, session.topic_id) if session and session.topic_id else None
    return report, session, topic


async def build_report_detail(
    db: AsyncSession, user: User, session_id
) -> ScoreReportDetailOut:
    """组装报告详情（practices 路由的 /{session_id}/report 调用）。"""
    report, session, topic = await _load_report_context(db, user, session_id)
    analyses = (
        await db.scalars(
            select(TurnAnalysis)
            .where(TurnAnalysis.report_id == report.id)
            .order_by(TurnAnalysis.seq)
        )
    ).all()

    brief = None
    if session is not None:
        brief = ReportSessionBrief(
            session_id=session.id,
            part=session.part,
            mode=session.mode,
            topic_name_en=topic.name_en if topic else None,
            topic_name_zh=topic.name_zh if topic else None,
            is_placement=session.topic_id is None and bool(session.question_ids),
            started_at=session.started_at,
            ended_at=session.ended_at,
        )

    return ScoreReportDetailOut(
        **{c.name: getattr(report, c.name) for c in report.__table__.columns},
        session=brief,
        turn_analyses=[TurnAnalysisOut.model_validate(a) for a in analyses],
    )


@router.get("/reports", response_model=list[ScoreReportListItemOut])
async def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScoreReportListItemOut]:
    rows = (
        await db.execute(
            select(ScoreReport, PracticeSession, Topic)
            .join(PracticeSession, ScoreReport.session_id == PracticeSession.id)
            .outerjoin(Topic, PracticeSession.topic_id == Topic.id)
            .where(ScoreReport.user_id == user.id)
            .order_by(ScoreReport.created_at.desc())
            .limit(limit)
        )
    ).all()
    items = []
    for report, session, topic in rows:
        items.append(
            ScoreReportListItemOut(
                report_id=report.id,
                session_id=report.session_id,
                status=report.status,
                overall_band=float(report.overall_band) if report.overall_band is not None else None,
                fluency=float(report.fluency) if report.fluency is not None else None,
                lexical=float(report.lexical) if report.lexical is not None else None,
                grammar=float(report.grammar) if report.grammar is not None else None,
                pronunciation=float(report.pronunciation) if report.pronunciation is not None else None,
                part=session.part,
                mode=session.mode,
                topic_name_en=topic.name_en if topic else None,
                topic_name_zh=topic.name_zh if topic else None,
                created_at=report.created_at,
            )
        )
    return items


@router.get("/reports/trend", response_model=TrendOut)
async def report_trend(
    limit: int = Query(default=30, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TrendOut:
    """提分趋势：已完成报告按时间升序的四维 + 综合序列。"""
    rows = (
        await db.execute(
            select(ScoreReport, PracticeSession)
            .join(PracticeSession, ScoreReport.session_id == PracticeSession.id)
            .where(ScoreReport.user_id == user.id, ScoreReport.status == "completed")
            .order_by(PracticeSession.started_at.asc())
            .limit(limit)
        )
    ).all()
    points = []
    for report, session in rows:
        anchor = (report.completed_at or report.created_at).astimezone(timezone.utc)
        points.append(
            TrendPoint(
                date=anchor.strftime("%Y-%m-%d"),
                overall_band=float(report.overall_band) if report.overall_band is not None else None,
                fluency=float(report.fluency) if report.fluency is not None else None,
                lexical=float(report.lexical) if report.lexical is not None else None,
                grammar=float(report.grammar) if report.grammar is not None else None,
                pronunciation=float(report.pronunciation) if report.pronunciation is not None else None,
            )
        )
    return TrendOut(points=points)
