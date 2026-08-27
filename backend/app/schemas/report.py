"""评分报告相关响应模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TurnAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    turn_id: uuid.UUID
    seq: int
    sentences: list[dict[str, Any]] | None
    pronunciation_detail: dict[str, Any] | None
    filler_hits: list[dict[str, Any]] | None


class ReportSessionBrief(BaseModel):
    """报告所属会话的简要信息（前端报告页头部展示）。"""

    session_id: uuid.UUID
    part: int
    mode: str
    topic_name_en: str | None = None
    topic_name_zh: str | None = None
    # 初始能力测评会话（topic 空 + 预选题集）：报告页据此弹目标分设置
    is_placement: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ScoreReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    status: str
    overall_band: float | None
    fluency: float | None
    lexical: float | None
    grammar: float | None
    pronunciation: float | None
    fluency_metrics: dict[str, Any] | None
    overall_comment_zh: str | None
    strengths: list[str] | None
    improvements: list[str] | None
    expression_upgrades: list[dict[str, Any]] | None
    low_confidence: list[str] | None
    model_versions: dict[str, Any] | None
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class ScoreReportDetailOut(ScoreReportOut):
    session: ReportSessionBrief | None = None
    turn_analyses: list[TurnAnalysisOut] = []


class ScoreReportListItemOut(BaseModel):
    """报告列表项：报告摘要 + 会话上下文。"""

    report_id: uuid.UUID
    session_id: uuid.UUID
    status: str
    overall_band: float | None
    fluency: float | None
    lexical: float | None
    grammar: float | None
    pronunciation: float | None
    part: int
    mode: str
    topic_name_en: str | None
    topic_name_zh: str | None
    created_at: datetime


class TrendPoint(BaseModel):
    date: str  # YYYY-MM-DD（按会话开始日）
    overall_band: float | None
    fluency: float | None
    lexical: float | None
    grammar: float | None
    pronunciation: float | None


class TrendOut(BaseModel):
    points: list[TrendPoint]
