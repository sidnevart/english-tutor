"""Pydantic schemas the LLM must fill via `complete_json` (JSON-mode targets)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QuestionPayload(BaseModel):
    prompt: str
    options: list[str] = Field(min_length=2)
    correct_index: int
    explanation: str = ""


class ReadingQuizPayload(BaseModel):
    questions: list[QuestionPayload] = Field(min_length=1)


class CleanedTranscript(BaseModel):
    content: str
