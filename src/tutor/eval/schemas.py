"""Pydantic schemas the LLM must fill via `complete_json` (JSON-mode targets)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QuestionPayload(BaseModel):
    prompt: str
    options: list[str] = Field(min_length=2)
    correct_index: int
    explanation: str = ""
    question_type: str = ""  # see eval/quiz_builder._QUESTION_TYPES


class ReadingQuizPayload(BaseModel):
    questions: list[QuestionPayload] = Field(min_length=1)


class CleanedTranscript(BaseModel):
    content: str


class Flashcard(BaseModel):
    term: str  # the word or idiom, exactly as it appears in the text
    kind: str = "word"  # "word" | "phrasal_verb" | "collocation" | "idiom" | "phrase"
    definition: str  # concise English definition
    example: str = ""  # a natural example sentence
    translation_ru: str = ""  # Russian translation of the term


class FlashcardPayload(BaseModel):
    cards: list[Flashcard] = Field(default_factory=list)


class SessionError(BaseModel):
    type: str = "grammar"  # grammar | vocab | phrasing
    error: str
    correction: str
    context: str = ""


class SessionFeedbackPayload(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    errors: list[SessionError] = Field(default_factory=list)
    recurring_fixed: list[str] = Field(default_factory=list)
    assessment: str = ""


class EssayPromptPayload(BaseModel):
    prompt: str
    type: str = "independent"
    passage: str = ""


class EssayCorrection(BaseModel):
    error: str
    correction: str
    type: str = "grammar"


class EssayEvalPayload(BaseModel):
    score: int = Field(ge=1, le=5)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    corrections: list[EssayCorrection] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
