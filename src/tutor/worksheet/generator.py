"""Vocabulary exercise models for the daily TOEFL file.

`FillBlank` and `CollocationMatch` are Pydantic models the LLM must fill via
`complete_json`.  They are used both by the daily-file vocab generator and by
the old (now removed) evening worksheet.  `VocabExercisesPayload` is the JSON
target for the lean vocab-only prompt used in `daily_file.generate_vocab_exercises`.

The heavier worksheet generation (`generate_worksheet`, `WorksheetPayload`, etc.)
was removed when the daily TOEFL file consolidated all task delivery into a
single morning-push file.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FillBlank(BaseModel):
    sentence: str  # sentence with ________ blank
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    source_word: str = ""  # the vocabulary word being tested


class CollocationMatch(BaseModel):
    word: str
    correct_partner: str
    distractors: list[str] = Field(min_length=3, max_length=3)


class VocabExercisesPayload(BaseModel):
    """LLM JSON target for the daily file's vocabulary exercises."""

    fill_blanks: list[FillBlank] = Field(default_factory=list)
    collocation_match: list[CollocationMatch] = Field(default_factory=list)