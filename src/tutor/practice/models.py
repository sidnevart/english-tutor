"""Stable domain vocabulary shared by the catalog, planner, and task runners."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Section(StrEnum):
    READING = "reading"
    SPEAKING = "speaking"
    WRITING = "writing"


class TaskType(StrEnum):
    COMPLETE_WORDS = "complete_words"
    DAILY_LIFE = "daily_life"
    ACADEMIC_PASSAGE = "academic_passage"
    LISTEN_REPEAT = "listen_repeat"
    INTERVIEW = "interview"
    BUILD_SENTENCE = "build_sentence"
    EMAIL = "email"
    ACADEMIC_DISCUSSION = "academic_discussion"

    @property
    def section(self) -> Section:
        if self in {self.COMPLETE_WORDS, self.DAILY_LIFE, self.ACADEMIC_PASSAGE}:
            return Section.READING
        if self in {self.LISTEN_REPEAT, self.INTERVIEW}:
            return Section.SPEAKING
        return Section.WRITING


class CatalogTask(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    version: int = 1
    section: Section
    task_type: TaskType
    topic_domain: str
    cefr: str = "B2-C1"
    skill_tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any]
    explanation: str = ""
    provenance: str = "bundled-original"
    source_url: str | None = None
    source_date: str | None = None
    validation_state: str = "accepted"
