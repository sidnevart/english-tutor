"""Schema-validated 0-5 evaluation for TOEFL open responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from tutor.db.repository import Repository
from tutor.interfaces.llm import LLMClient
from tutor.practice.models import Section, TaskType
from tutor.progress.tracker import IssueInput, ProgressTracker


class RubricIssue(BaseModel):
    category: str
    skill_code: str
    canonical_key: str
    original_excerpt: str
    correction: str
    explanation: str
    severity: int = Field(default=1, ge=1, le=3)


class CriterionScore(BaseModel):
    criterion: str
    score: float = Field(ge=0, le=5)
    comment: str = ""


class RubricEvaluation(BaseModel):
    score: float = Field(default=0, ge=0, le=5)
    confidence: float = Field(default=0.5, ge=0, le=1)
    criteria: list[CriterionScore] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    issues: list[RubricIssue] = Field(default_factory=list)
    successful_checks: list[str] = Field(default_factory=list)
    explanation: str = ""


RUBRICS = {
    TaskType.INTERVIEW: (
        "Interview: relevance, elaboration, pace, intelligibility evidence, grammar, "
        "vocabulary, coherence, and task completion."
    ),
    TaskType.EMAIL: (
        "Email: communicative purpose, required details, register, organization, "
        "grammar, and vocabulary."
    ),
    TaskType.ACADEMIC_DISCUSSION: (
        "Academic discussion: relevance, development, response to other views, "
        "academic tone, organization, grammar, and vocabulary."
    ),
}


class RubricEvaluator:
    def __init__(self, repo: Repository, llm: LLMClient, tracker: ProgressTracker) -> None:
        self.repo = repo
        self.llm = llm
        self.tracker = tracker

    async def evaluate(self, attempt_id: int) -> RubricEvaluation | None:
        attempt = self.repo.attempt(attempt_id)
        if not attempt:
            raise LookupError("Attempt not found")
        task_type = TaskType(str(attempt["task_type"]))
        if task_type not in RUBRICS:
            return None
        items = self.repo.attempt_items(attempt_id)
        payload = json.loads(str(attempt["payload_json"]))
        responses = [str(item["response_text"]) for item in items]
        metrics = [json.loads(str(item["metrics_json"])) for item in items]
        section = Section(str(attempt["section"]))
        user_id = int(attempt["user_id"])
        existing = self.repo.unresolved_issues(user_id, section.value)
        system = (
            "You are a careful TOEFL practice evaluator. This is a training estimate, not an "
            "official section score. Apply this 0-5 rubric. Only put a canonical issue key in "
            "successful_checks when this response directly demonstrates that exact tracked "
            "skill. Omission is not success; never invent or rename a tracked key: "
            + RUBRICS[task_type]
        )
        user = json.dumps(
            {
                "task_type": task_type.value,
                "prompt": payload,
                "responses": responses,
                "speech_metrics": metrics,
                "tracked_issues": existing,
            },
            ensure_ascii=False,
        )
        try:
            result = await self.llm.complete_json(system, user, RubricEvaluation)
        except Exception:
            return None

        local_date = datetime.now(UTC).date()
        failed_keys = {issue.canonical_key for issue in result.issues}
        existing_keys = {str(issue["canonical_key"]) for issue in existing}
        with self.repo.conn:
            self.repo.complete_attempt_evaluation(
                attempt_id, result.score, 5.0, result.model_dump(), commit=False
            )
            for issue in result.issues:
                self.tracker.record_issue(
                    user_id,
                    IssueInput(
                        section=section,
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
                    attempt_id=attempt_id,
                    commit=False,
                )
            for key in set(result.successful_checks) & existing_keys:
                if key not in failed_keys:
                    self.tracker.record_success(
                        user_id, key, local_date, attempt_id=attempt_id, commit=False
                    )
        return result

    async def retry_pending(self) -> int:
        completed = 0
        for attempt_id in self.repo.pending_evaluation_ids():
            if await self.evaluate(attempt_id) is not None:
                completed += 1
        return completed
