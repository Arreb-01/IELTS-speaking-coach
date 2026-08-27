"""学习路径 REST（Part E M3）。

GET /plan/week：本周 7 天概览 + 指定日任务详情；空缺日惰性现场生成。
POST /plan/tasks/{id}/complete：完成任务（打卡）。
POST /plan/tasks/{id}/skip：跳过不计完成，立即生成同型替补。
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.base import get_db
from app.db.models import DailyTask, ScoreReport, User
from app.schemas.progress import (
    PlanDayOut,
    PlanWeekOut,
    TaskActionMeta,
    TaskCompleteOut,
    TaskOut,
)
from app.services.progress import stats
from app.services.progress.recommender import ensure_range, replace_skipped_task
from app.services.progress.stats import local_date

router = APIRouter()


def _f(value) -> float | None:
    return float(value) if value is not None else None


async def _predict_current(db, user: User) -> tuple[float | None, str | None]:
    """(当前预测 Band, eta 文案)。"""
    overalls = (
        await db.scalars(
            select(ScoreReport.overall_band)
            .where(ScoreReport.user_id == user.id, ScoreReport.status == "completed")
            .order_by(ScoreReport.created_at.desc())
            .limit(stats.PREDICT_WINDOW)
        )
    ).all()
    band, _hint = stats.predicted_band([float(v) for v in overalls if v is not None])
    return band, None


@router.get("/week", response_model=PlanWeekOut)
async def plan_week(
    selected: date | None = Query(default=None, alias="date"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PlanWeekOut:
    today = local_date(datetime.now(timezone.utc))
    selected = selected or today
    week_start = today - timedelta(days=today.weekday())  # 本周一

    # 空缺日现场生成（幂等：只补完全没有任务行的日子）
    await ensure_range(user.id, week_start, days=7)

    rows = (
        await db.scalars(
            select(DailyTask)
            .where(
                DailyTask.user_id == user.id,
                DailyTask.plan_date >= week_start,
                DailyTask.plan_date < week_start + timedelta(days=7),
            )
            .order_by(DailyTask.plan_date, DailyTask.sort)
        )
    ).all()

    by_day: dict[date, list[DailyTask]] = {}
    for task in rows:
        by_day.setdefault(task.plan_date, []).append(task)

    days = []
    week_done = 0
    week_active = 0  # done + pending（skipped 不计完成率）
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        tasks = by_day.get(day, [])
        done = sum(1 for t in tasks if t.status == "done")
        pending = sum(1 for t in tasks if t.status == "pending")
        days.append(
            PlanDayOut(date=day, done_count=done, total_count=len(tasks), is_today=(day == today))
        )
        week_done += done
        week_active += done + pending

    selected_tasks = sorted(by_day.get(selected, []), key=lambda t: (t.sort, t.created_at))

    predicted, _eta_hint = await _predict_current(db, user)
    target = _f(user.target_band)
    gain_points = [
        ((report.completed_at or report.created_at), float(report.overall_band))
        for report in (
            await db.scalars(
                select(ScoreReport)
                .where(
                    ScoreReport.user_id == user.id,
                    ScoreReport.status == "completed",
                    ScoreReport.overall_band.is_not(None),
                )
                .order_by(ScoreReport.created_at.asc())
                .limit(100)
            )
        ).all()
    ]
    weekly_gain = stats.weekly_gain_from_history(gain_points, datetime.now(timezone.utc))
    eta_text_value = stats.eta_text(target, predicted, weekly_gain)

    completion = round(week_done / week_active * 100) if week_active else 0

    return PlanWeekOut(
        week_start=week_start,
        days=days,
        selected_date=selected,
        tasks=[TaskOut.model_validate(t) for t in selected_tasks],
        meta=TaskActionMeta(
            current_band=predicted,
            target_band=target,
            predicted_band=predicted,
            eta_text=eta_text_value,
            weekly_completion=completion,
        ),
    )


async def _load_own_task(db, task_id: uuid.UUID, user: User) -> DailyTask:
    task = await db.get(DailyTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    return task


@router.post("/tasks/{task_id}/complete", response_model=TaskCompleteOut)
async def complete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskCompleteOut:
    task = await _load_own_task(db, task_id, user)
    if task.status == "skipped":
        raise HTTPException(422, "已跳过的任务不能标记完成")
    if task.status != "done":
        task.status = "done"
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(task)
    return TaskCompleteOut(id=task.id, status=task.status)


@router.post("/tasks/{task_id}/skip", response_model=TaskCompleteOut)
async def skip_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TaskCompleteOut:
    task = await _load_own_task(db, task_id, user)
    if task.status == "done":
        raise HTTPException(422, "已完成的任务不能跳过")
    if task.status != "skipped":
        task.status = "skipped"
        await db.commit()
        await db.refresh(task)
    await replace_skipped_task(user.id, task)
    return TaskCompleteOut(id=task.id, status=task.status)
