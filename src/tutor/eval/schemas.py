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


class Flashcard(BaseModel):
    term: str  # the word or idiom, exactly as it appears in the text
    kind: str = "word"  # "word" | "idiom"
    definition: str  # concise English definition
    example: str = ""  # a natural example sentence


class FlashcardPayload(BaseModel):
    cards: list[Flashcard] = Field(default_factory=list)
