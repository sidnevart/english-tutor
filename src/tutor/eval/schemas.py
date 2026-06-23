"""Pydantic schemas the LLM must fill via `complete_json` (JSON-mode targets)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QuestionPayload(BaseModel):
    prompt: str
    options: list[str] = Field(min_length=2)
    correct_index: int
    # For multi-select questions (TOEFL "summary": pick 3 of 6). When non-empty
    # the question is graded on the chosen SET; correct_index is then ignored.
    correct_indices: list[int] = Field(default_factory=list)
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
    passage: str = ""  # reading passage (integrated task)
    lecture: str = ""  # lecture transcript that responds to the passage (integrated task)


class EssayCorrection(BaseModel):
    error: str
    correction: str
    type: str = "grammar"


class EssayEvalPayload(BaseModel):
    score: int = Field(ge=0, le=5)  # official TOEFL writing rubric (0-5)
    scaled_30: int = Field(default=0, ge=0, le=30)  # estimated scaled score (0-30)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    corrections: list[EssayCorrection] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class SpeakingTaskPayload(BaseModel):
    """A generated TOEFL speaking task. Integrated tasks fill reading/listening."""

    task_type: str = "independent"  # independent | campus | concept | lecture
    prompt: str  # the spoken question the learner must answer
    reading: str = ""  # short reading (campus announcement / academic passage)
    listening: str = ""  # conversation / lecture transcript to be read aloud (TTS)


class SpeakingEvalPayload(BaseModel):
    """TOEFL speaking rubric: three traits scored 0-4, plus overall + scaled."""

    delivery: int = Field(ge=0, le=4)
    language_use: int = Field(ge=0, le=4)
    topic_development: int = Field(ge=0, le=4)
    score: int = Field(ge=0, le=4)  # overall 0-4
    scaled_30: int = Field(default=0, ge=0, le=30)  # estimated scaled score (0-30)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    feedback: str = ""
