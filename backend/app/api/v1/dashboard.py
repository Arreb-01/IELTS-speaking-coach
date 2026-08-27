"""Dashboard 一站式聚合端点（Part E M1）。

GET /dashboard/overview：hero 统计 + 四维雷达 + 提分趋势 + 今日推荐 +
最近练习，一次请求避免前端拼 4 个接口。详细趋势仍可复用 /reports/trend。
GET /dashboard/weakness：薄弱项分析（四维序列 + 定向话题推荐）。
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import DailyTask, PracticeSession, ScoreReport, Topic, User
from app.schemas.progress import (
    DashboardOverviewOut,
    DashboardRadar,
    HeroStats,
    PredictedBand,
    RecentPracticeOut,
    TaskOut,
    TrendPointOut,
    WeaknessOut,
    WeaknessSuggestionOut,
)
from app.services.progress import stats
from app.services.progress.recommender import (
    ensure_range,
    finalize_stats,
    load_context,
    pick_topic,
)
from app.services.progress.stats import DIMENSIONS, local_date

router = APIRouter()


def _f(value) -> float | None:
    return float(value) if value is not None else None


@router.get("/overview", response_model=DashboardOverviewOut)
async def overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardOverviewOut:
    now_utc = datetime.now(timezone.utc)
    today = local_date(now_utc)

    # ---- 近 5 次 completed 报告（新→旧）----
    recent = (
        await db.execute(
            select(ScoreReport, PracticeSession)
            .join(PracticeSession, ScoreReport.session_id == PracticeSession.id)
            .where(ScoreReport.user_id == user.id, ScoreReport.status == "completed")
            .order_by(ScoreReport.created_at.desc())
            .limit(stats.PREDICT_WINDOW)
        )
    ).all()
    has_any_report = bool(recent)

    # 老用户兼容：已有历史报告即视为具备能力基线，不再强制初始测评
    needs_placement = user.placement_at is None and not has_any_report

    any_session = await db.scalar(
        select(PracticeSession.id)
        .where(PracticeSession.user_id == user.id, PracticeSession.status == "completed")
        .limit(1)
    )

    # ---- 雷达与弱项 ----
    dim_values: dict[str, list[float]] = {}
    for report, _session in recent:
        for dim in DIMENSIONS:
            value = getattr(report, dim)
            if value is not None:
                dim_values.setdefault(dim, []).append(float(value))
    averages = stats.dimension_averages(dim_values)
    weaknesses = stats.weakness_order(averages)

    overalls_desc = [
        float(r.overall_band) for r, _s in recent if r.overall_band is not None
    ]
    band, hint = stats.predicted_band(overalls_desc)

    # ---- 连续打卡（近 90 天 completed 会话的本地日期集合）----
    since = now_utc - timedelta(days=90)
    sessions_recent = (
        await db.scalars(
            select(PracticeSession.started_at).where(
                PracticeSession.user_id == user.id,
                PracticeSession.status == "completed",
                PracticeSession.started_at >= since,
            )
        )
    ).all()
    practiced_dates = {local_date(dt) for dt in sessions_recent}
    streak = stats.streak_days(practiced_dates, today)

    # ---- 单次练习平均（近 7 天 completed 会话时长）----
    week_ago = now_utc - timedelta(days=7)
    duration_rows = (
        await db.execute(
            select(PracticeSession.started_at, PracticeSession.ended_at).where(
                PracticeSession.user_id == user.id,
                PracticeSession.status == "completed",
                PracticeSession.started_at >= week_ago,
                PracticeSession.ended_at.is_not(None),
            )
        )
    ).all()
    avg_minutes = stats.avg_session_minutes(
        [
            (end - start).total_seconds()
            for start, end in duration_rows
            if end is not None and end > start
        ]
    )

    # ---- 较上周变化 / 预计达成 ----
    history = (
        await db.execute(
            select(ScoreReport, PracticeSession)
            .join(PracticeSession, ScoreReport.session_id == PracticeSession.id)
            .where(ScoreReport.user_id == user.id, ScoreReport.status == "completed")
            .order_by(ScoreReport.created_at.asc())
            .limit(100)
        )
    ).all()
    this_week_start = today - timedelta(days=today.weekday())
    last_week_start = this_week_start - timedelta(days=7)
    by_local_day: dict = {}
    for report, session in history:
        value = _f(report.overall_band)
        if value is not None:
            anchor = report.completed_at or report.created_at
            by_local_day[local_date(anchor)] = value

    def _last_of_week(start_day, end_day):
        days = [(d, v) for d, v in by_local_day.items() if start_day <= d < end_day]
        return max(days)[1] if days else None

    week_delta = stats.week_delta(
        _last_of_week(this_week_start, this_week_start + timedelta(days=7)),
        _last_of_week(last_week_start, this_week_start),
    )
    gain_points = sorted((dt, v) for dt, v in by_local_day.items() if v is not None)
    weekly_gain = stats.weekly_gain_from_history(gain_points, now_utc)
    eta = stats.eta_text(_f(user.target_band), band, weekly_gain)

    # ---- 今日任务（无任务行的日子现场生成一次，懒加载兜底）----
    if not needs_placement and has_any_report:
        await ensure_range(user.id, today, days=1)
    today_tasks = (
        await db.scalars(
            select(DailyTask)
            .where(DailyTask.user_id == user.id, DailyTask.plan_date == today)
            .order_by(DailyTask.sort)
        )
    ).all()
    today_done = sum(1 for t in today_tasks if t.status == "done")

    # ---- 提分趋势（最近 15 点升序）----
    trend_desc = (
        await db.execute(
            select(ScoreReport, PracticeSession)
            .join(PracticeSession, ScoreReport.session_id == PracticeSession.id)
            .where(ScoreReport.user_id == user.id, ScoreReport.status == "completed")
            .order_by(ScoreReport.created_at.desc())
            .limit(15)
        )
    ).all()
    trend_points = [
        TrendPointOut(
            date=(report.completed_at or report.created_at)
            .astimezone(stats.LOCAL_TZ)
            .strftime("%Y-%m-%d"),
            overall_band=_f(report.overall_band),
            fluency=_f(report.fluency),
            lexical=_f(report.lexical),
            grammar=_f(report.grammar),
            pronunciation=_f(report.pronunciation),
        )
        for report, _session in reversed(trend_desc)
    ]

    # ---- 最近练习（5 条）----
    recent_sessions = (
        await db.execute(
            select(PracticeSession, Topic, ScoreReport)
            .join(Topic, PracticeSession.topic_id == Topic.id, isouter=True)
            .join(ScoreReport, ScoreReport.session_id == PracticeSession.id, isouter=True)
            .where(PracticeSession.user_id == user.id, PracticeSession.status == "completed")
            .order_by(PracticeSession.started_at.desc())
            .limit(5)
        )
    ).all()
    recent_items = [
        RecentPracticeOut(
            session_id=session.id,
            part=session.part,
            mode=session.mode,
            topic_name_en=topic.name_en if topic else None,
            topic_name_zh=topic.name_zh if topic else None,
            overall_band=_f(report.overall_band) if report else None,
            report_status=report.status if report else None,
            started_at=session.started_at,
        )
        for session, topic, report in recent_sessions
    ]

    return DashboardOverviewOut(
        needs_placement=needs_placement,
        has_any_practice=bool(any_session),
        hero=HeroStats(
            target_band=_f(user.target_band),
            predicted=PredictedBand(band=band, hint=hint),
            streak_days=streak,
            today_done=today_done,
            today_total=len(today_tasks),
            avg_session_minutes=avg_minutes,
            week_delta=week_delta,
            eta_text=eta,
        ),
        radar=(
            DashboardRadar(
                fluency=averages.get("fluency"),
                lexical=averages.get("lexical"),
                grammar=averages.get("grammar"),
                pronunciation=averages.get("pronunciation"),
            )
            if averages
            else None
        ),
        radar_order=[dim for dim, _avg in weaknesses],
        trend_points=trend_points,
        recommendations=[TaskOut.model_validate(t) for t in today_tasks],
        recent_practices=recent_items,
    )


@router.get("/weakness", response_model=WeaknessOut)
async def weakness(
    dimension: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WeaknessOut:
    """四维近 5 次序列 + 弱项定向话题推荐（6 个）。"""
    ctx = await load_context(db, user.id)
    finalize_stats(ctx)

    primary = dimension if dimension in DIMENSIONS else None
    primary_avg: float | None = None
    if primary is None and ctx.ordered_weaknesses:
        primary, primary_avg = ctx.ordered_weaknesses[0]
    elif primary is not None:
        primary_avg = ctx.avgs.get(primary)

    suggestions: list[WeaknessSuggestionOut] = []
    if ctx.report_count:
        need_p2 = primary == "fluency"
        seen: set[uuid.UUID] = set()
        while len(suggestions) < 6:
            topic = pick_topic(ctx, need_p2=need_p2)
            if topic is None or topic.id in seen:
                break
            seen.add(topic.id)
            if topic.tag == "retained":
                reason = "巩固复习，保持手感"
            elif topic.id in ctx.practiced_topic_ids:
                reason = "再次练习，检验提升"
            elif topic.tag == "must":
                reason = "必考话题，优先掌握"
            else:
                reason = "新题储备，拓宽覆盖"
            suggestions.append(
                WeaknessSuggestionOut(
                    topic_id=topic.id,
                    name_en=topic.name_en,
                    name_zh=topic.name_zh,
                    category=topic.category,
                    tag=topic.tag,
                    reason_zh=reason,
                )
            )

    return WeaknessOut(
        dim_values={dim: values[: stats.PREDICT_WINDOW] for dim, values in ctx.dim_values.items()},
        averages=ctx.avgs,
        primary_dimension=primary,
        primary_avg=primary_avg,
        stable_dims=sorted(ctx.stable_dims),
        suggestions=suggestions,
    )
