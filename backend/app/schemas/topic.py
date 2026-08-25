import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    part: int
    content_en: str
    cue_card: dict[str, Any] | None
    sort: int


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name_en: str
    name_zh: str | None
    category: str | None
    tag: str | None
    question_count: int = 0


class TopicDetailOut(TopicOut):
    questions: list[QuestionOut] = []


class PracticeTurnOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    question_text: str | None
    is_followup: bool
    user_transcript: str | None
    has_audio: bool = False
    started_at: datetime | None
    ended_at: datetime | None


class PracticeSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    mode: str
    part: int
    topic_id: uuid.UUID | None
    status: str
    accent: str
    speed: str
    started_at: datetime
    ended_at: datetime | None


class PracticeSessionDetailOut(PracticeSessionOut):
    topic: TopicOut | None = None
    turns: list[PracticeTurnOut] = []


class PracticeCreateRequest(BaseModel):
    topic_id: uuid.UUID
    part: int = Field(ge=1, le=3)
    mode: str = "practice"
    accent: str = "en_female_anna"
    speed: str = "normal"


class PracticeCreateResponse(BaseModel):
    session_id: uuid.UUID
    ws_ticket: str
    ws_path: str
