"""Pydantic schemas the LLM must fill via `complete_json` (JSON-mode targets).

Only the error-capture contract remains: `end_session` asks the LLM for a
`SessionFeedbackPayload` (strengths + a list of `SessionError`s), which is then
persisted into `session_error`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


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
