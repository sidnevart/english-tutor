from __future__ import annotations

from conftest import TEST_USER

from tutor.eval.email import EmailCheckResult, StandaloneEmailChecker
from tutor.progress.tracker import ProgressTracker


class FakeEmailLLM:
    def __init__(self) -> None:
        self.system = ""
        self.user = ""

    async def complete_json(self, system, user, schema):
        self.system = system
        self.user = user
        assert schema is EmailCheckResult
        return EmailCheckResult(
            overall_assessment="Clear and polite, with one agreement error.",
            confidence=0.9,
            strengths=["The request is easy to understand."],
            issues=[
                {
                    "category": "grammar",
                    "skill_code": "subject_verb_agreement",
                    "canonical_key": "grammar:subject_verb_agreement",
                    "original_excerpt": "students is",
                    "correction": "students are",
                    "explanation": "Use a plural verb with students.",
                    "severity": 2,
                }
            ],
            revised_email="Dear Coordinator,\n\nThe students are ready to help.\n\nBest,\nAlex",
        )


async def test_standalone_email_check_records_writing_issues_without_an_attempt(repo) -> None:
    llm = FakeEmailLLM()
    tracker = ProgressTracker(repo)
    checker = StandaloneEmailChecker(repo, llm, tracker)

    result = await checker.check(
        TEST_USER, "Dear Coordinator,\n\nThe students is ready to help.\n\nBest,\nAlex"
    )

    assert result is not None
    assert "official TOEFL score" in llm.system
    assert "students is" in llm.user
    issue = tracker.issue(TEST_USER, "grammar:subject_verb_agreement")
    assert issue is not None
    assert issue["section"] == "writing"
    attempts = repo.conn.execute("SELECT COUNT(*) FROM practice_attempt").fetchone()[0]
    assert attempts == 0


async def test_failed_standalone_email_check_records_nothing(repo) -> None:
    class BrokenLLM:
        async def complete_json(self, system, user, schema):
            raise RuntimeError("offline")

    checker = StandaloneEmailChecker(repo, BrokenLLM(), ProgressTracker(repo))

    result = await checker.check(TEST_USER, "Dear Coordinator, please help me.")

    assert result is None
    issue_count = repo.conn.execute("SELECT COUNT(*) FROM learning_issue").fetchone()[0]
    assert issue_count == 0
