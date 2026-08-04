"""Schema-validated review for an email supplied outside daily practice."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from tutor.db.repository import Repository
from tutor.eval.rubric import RubricIssue
from tutor.interfaces.llm import LLMClient
from tutor.practice.models import Section
from tutor.progress.tracker import IssueInput, ProgressTracker


class EmailCheckResult(BaseModel):
    overall_assessment: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)
    strengths: list[str] = Field(default_factory=list, max_length=5)
    issues: list[RubricIssue] = Field(default_factory=list, max_length=8)
    revised_email: str = ""


class StandaloneEmailChecker:
    def __init__(self, repo: Repository, llm: LLMClient, tracker: ProgressTracker) -> None:
        self.repo = repo
        self.llm = llm
        self.tracker = tracker

    async def check(self, user_id: int, email_text: str) -> EmailCheckResult | None:
        existing = self.repo.unresolved_issues(user_id, Section.WRITING.value)
        system = (
            "You review a standalone English email. Evaluate only evidence in the supplied "
            "text: email structure, clarity, organization, tone, register, grammar, vocabulary, "
            "and phrasing. Do not assign an official TOEFL score or infer a missing task prompt. "
            "Preserve the writer's intended meaning in revised_email. Return concise, actionable "
            "feedback. Reuse a tracked canonical_key when the same skill appears; otherwise use "
            "a stable category:skill_code key."
        )
        user = json.dumps(
            {"email": email_text, "tracked_writing_issues": existing}, ensure_ascii=False
        )
        try:
            result = await self.llm.complete_json(system, user, EmailCheckResult)
            local_date = datetime.now(UTC).date()
            with self.repo.conn:
                for issue in result.issues:
                    self.tracker.record_issue(
                        user_id,
                        IssueInput(
                            section=Section.WRITING,
                            category=issue.category,
                            skill_code=issue.skill_code,
                            canonical_key=issue.canonical_key,
                            original_excerpt=issue.original_excerpt,
                            correction=issue.correction,
                            explanation=issue.explanation,
                            severity=issue.severity,
                            confidence=result.confidence,
                        ),
                        local_date=local_date,
                        commit=False,
                    )
        except Exception:
            return None
        return result
