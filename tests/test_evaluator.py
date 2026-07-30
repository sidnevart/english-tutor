from __future__ import annotations

from datetime import date, timedelta

from conftest import TEST_USER

from tutor.catalog import BundledCatalog
from tutor.eval.rubric import RubricEvaluation, RubricEvaluator
from tutor.practice.engine import PracticeEngine
from tutor.practice.models import Section, TaskType
from tutor.practice.planner import DailyPlanner
from tutor.progress.tracker import IssueInput, ProgressTracker


class FakeLLM:
    def __init__(self) -> None:
        self.system = ""

    async def complete_json(self, system, user, schema):
        self.system = system
        assert schema is RubricEvaluation
        return RubricEvaluation(
            score=3,
            confidence=0.9,
            strengths=["Relevant response"],
            issues=[
                {
                    "category": "grammar",
                    "skill_code": "subject_verb_agreement",
                    "canonical_key": "grammar:subject_verb_agreement",
                    "original_excerpt": "students is",
                    "correction": "students are",
                    "explanation": "Use a plural verb.",
                    "severity": 2,
                }
            ],
            explanation="Clear but contains a recurring agreement error.",
        )


async def test_open_response_uses_task_specific_rubric_and_updates_profile(repo) -> None:
    planner = DailyPlanner(repo, BundledCatalog.load())
    plans = [
        planner.ensure_plan(TEST_USER, date(2026, 7, 30) + timedelta(days=i)) for i in range(6)
    ]
    entry = next(
        entry for plan in plans for entry in plan.entries if entry.task_type is TaskType.EMAIL
    )
    engine = PracticeEngine(repo)
    engine.start(TEST_USER, entry.id)
    completed = engine.submit_current(TEST_USER, "Dear Coordinator, students is ready to help.")
    llm = FakeLLM()

    result = await RubricEvaluator(repo, llm, ProgressTracker(repo)).evaluate(completed.id)

    assert "email" in llm.system.lower()
    assert result.score == 3
    assert repo.attempt(completed.id)["evaluation_state"] == "complete"
    assert ProgressTracker(repo).issue(TEST_USER, "grammar:subject_verb_agreement") is not None


async def test_evaluation_failure_keeps_attempt_pending(repo) -> None:
    class BrokenLLM:
        async def complete_json(self, system, user, schema):
            raise RuntimeError("offline")

    planner = DailyPlanner(repo, BundledCatalog.load())
    plan = planner.ensure_plan(TEST_USER, date(2026, 7, 30))
    entry = plan.entry(Section.SPEAKING)
    # Create an interview plan explicitly by using the following day.
    entry = planner.ensure_plan(TEST_USER, date(2026, 7, 31)).entry(Section.SPEAKING)
    engine = PracticeEngine(repo)
    attempt = engine.start(TEST_USER, entry.id)
    while attempt.status == "active":
        attempt = engine.submit_current(
            TEST_USER, "I think this helps students because it is useful."
        )

    result = await RubricEvaluator(repo, BrokenLLM(), ProgressTracker(repo)).evaluate(attempt.id)

    assert result is None
    assert repo.attempt(attempt.id)["evaluation_state"] == "pending"


async def test_evaluator_receives_tracked_issues_and_records_explicit_success(repo) -> None:
    class SuccessLLM:
        async def complete_json(self, system, user, schema):
            assert "grammar:articles" in user
            return RubricEvaluation(
                score=4,
                confidence=0.9,
                successful_checks=["grammar:articles"],
                explanation="The article is used correctly in this response.",
            )

    planner = DailyPlanner(repo, BundledCatalog.load())
    plans = [
        planner.ensure_plan(TEST_USER, date(2026, 7, 30) + timedelta(days=i)) for i in range(6)
    ]
    entry = next(
        entry for plan in plans for entry in plan.entries if entry.task_type is TaskType.EMAIL
    )
    tracker = ProgressTracker(repo)
    tracker.record_issue(
        TEST_USER,
        IssueInput(
            section=Section.WRITING,
            category="grammar",
            skill_code="articles",
            canonical_key="grammar:articles",
            original_excerpt="I visited library.",
            correction="I visited the library.",
            explanation="Use the definite article for a specific place.",
        ),
        local_date=date(2026, 7, 29),
    )
    engine = PracticeEngine(repo)
    engine.start(TEST_USER, entry.id)
    completed = engine.submit_current(TEST_USER, "I visited the library before writing.")

    await RubricEvaluator(repo, SuccessLLM(), tracker).evaluate(completed.id)

    assert tracker.issue(TEST_USER, "grammar:articles")["state"] == "improving"
