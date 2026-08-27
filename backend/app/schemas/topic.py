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


class SampleAnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID | None
    part: int
    text_en: str
    summary_zh: str | None
    source: str


class ExpressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic_id: uuid.UUID
    text_en: str
    meaning_zh: str
    example_en: str | None


class TopicLinkOut(BaseModel):
    group_name: str
    linked_topic_names: list[str] = []
    shared_answer: SampleAnswerOut


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name_en: str
    name_zh: str | None
    category: str | None
    tag: str | None
    question_count: int = 0


class TopicListOut(BaseModel):
    items: list[TopicOut]
    total: int
    page: int
    page_size: int


class QuestionWithAnswerOut(QuestionOut):
    sample_answer: SampleAnswerOut | None = None


class TopicDetailOut(TopicOut):
    questions: list[QuestionWithAnswerOut] = []
    # topic 级范文（P2 主范文 / linked 串联范文）
    sample_answers: list[SampleAnswerOut] = []
    expressions: list[ExpressionOut] = []
    links: list[TopicLinkOut] = []


class VocabWordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    word: str
    context_en: str | None
    source_topic_id: uuid.UUID | None
    source_topic_name: str | None = None
    is_favorite: bool
    created_at: datetime


class VocabWordCreateRequest(BaseModel):
    word: str = Field(min_length=1, max_length=200)
    context_en: str | None = None
    source_topic_id: uuid.UUID | None = None


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
