"""Pydantic domain models — the data that flows through the pipeline."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from tutor.domain.enums import (
    Cadence,
    ContentType,
    DeliveryStatus,
    QuizKind,
    SourceType,
)


class RawItem(BaseModel):
    """A piece of content as produced by an ingestor, before it is stored."""

    source_type: SourceType
    source_ref: str  # channel id or feed name/url
    external_id: str  # stable dedup key within a source
    content_type: ContentType
    title: str = ""
    url: str = ""
    body_text: str = ""  # may be empty for lazily-transcribed podcasts
    audio_url: str = ""
    duration_sec: int | None = None
    lang: str = "en"
    cadence_bucket: Cadence | None = None
    published_at: datetime | None = None


class ContentItem(BaseModel):
    """A stored content row, including its lifecycle state."""

    id: int
    user_id: int
    source_type: SourceType
    source_ref: str
    external_id: str
    content_type: ContentType
    title: str = ""
    url: str = ""
    body_text: str = ""
    audio_url: str = ""
    duration_sec: int | None = None
    lang: str = "en"
    cadence_bucket: Cadence | None = None
    status: DeliveryStatus = DeliveryStatus.NEW
    fetched_at: datetime
    delivered_at: datetime | None = None
    reviewed_at: datetime | None = None


class VocabItem(BaseModel):
    id: int | None = None
    content_id: int
    word: str
    lemma: str = ""
    definition: str = ""
    example: str = ""
    freq_rank: float = 0.0  # Zipf frequency; lower = rarer


class QuizQuestion(BaseModel):
    id: int | None = None
    quiz_id: int | None = None
    prompt: str
    options: list[str] = Field(min_length=2)
    correct_index: int
    explanation: str = ""
    question_type: str = ""  # see eval/quiz_builder._QUESTION_TYPES


class Quiz(BaseModel):
    id: int | None = None
    content_id: int
    kind: QuizKind
    questions: list[QuizQuestion] = Field(default_factory=list)


class Attempt(BaseModel):
    id: int | None = None
    quiz_question_id: int
    user_id: int
    chosen_index: int
    is_correct: bool
    answered_at: datetime | None = None


class Card(BaseModel):
    """An Anki note to be written by an AnkiSink."""

    front: str
    back: str
    tags: list[str] = Field(default_factory=list)


class AnkiResult(BaseModel):
    sink: str
    deck: str
    count: int
    apkg_path: str | None = None
    note_ids: list[int] = Field(default_factory=list)
