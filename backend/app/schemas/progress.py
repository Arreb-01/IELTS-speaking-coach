"""学习路径与 Dashboard 的响应模型（Part E）。"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class PredictedBand(BaseModel):
    band: float | None = None
    hint: str = ""


class DashboardRadar(BaseModel):
    """四维均值（近 5 次 completed 报告），无数据时为 None。"""

    fluency: float | None = None
    lexical: float | None = None
    grammar: float | None = None
    pronunciation: float | None = None


class TrendPointOut(BaseModel):
    date: str  # YYYY-MM-DD
    overall_band: float | None
    fluency: float | None
    lexical: float | None
    grammar: float | None
    pronunciation: float | None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_date: date
    task_type: Literal["topic", "special", "corpus"]
    dimension: str | None
    topic_id: uuid.UUID | None
    part: int | None
    title_zh: str
    desc_zh: str
    payload: dict[str, Any] | None
    status: Literal["pending", "done", "skipped"]
    sort: int


class RecentPracticeOut(BaseModel):
    session_id: uuid.UUID
    part: int
    mode: str
    topic_name_en: str | None
    topic_name_zh: str | None
    overall_band: float | None
    report_status: str | None
    started_at: datetime


class HeroStats(BaseModel):
    target_band: float | None
    predicted: PredictedBand
    streak_days: int
    today_done: int
    today_total: int
    avg_session_minutes: float | None
    week_delta: float | None
    eta_text: str | None


class DashboardOverviewOut(BaseModel):
    needs_placement: bool
    has_any_practice: bool
    hero: HeroStats
    radar: DashboardRadar | None
    radar_order: list[str]  # 弱项升序的维度名（前端角标提示）
    trend_points: list[TrendPointOut]
    recommendations: list[TaskOut]
    recent_practices: list[RecentPracticeOut]


class WeaknessSuggestionOut(BaseModel):
    topic_id: uuid.UUID
    name_en: str
    name_zh: str | None
    category: str | None
    tag: str | None
    reason_zh: str


class WeaknessOut(BaseModel):
    """薄弱项分析：四维近 5 次序列 + 一号弱项 + 定向推荐话题。"""

    dim_values: dict[str, list[float]]
    averages: dict[str, float]
    primary_dimension: str | None
    primary_avg: float | None
    stable_dims: list[str]
    suggestions: list[WeaknessSuggestionOut]


class PlanDayOut(BaseModel):
    date: date
    done_count: int
    total_count: int
    is_today: bool


class TaskActionMeta(BaseModel):
    current_band: float | None
    target_band: float | None
    predicted_band: float | None
    eta_text: str | None
    weekly_completion: int  # 完成率百分比（done / (pending+done)）


class PlanWeekOut(BaseModel):
    week_start: date
    days: list[PlanDayOut]
    selected_date: date
    tasks: list[TaskOut]
    meta: TaskActionMeta


class TaskCompleteOut(BaseModel):
    id: uuid.UUID
    status: str


class PlacementStartOut(BaseModel):
    session_id: uuid.UUID
    ws_ticket: str
    ws_path: str
    total_questions: int
