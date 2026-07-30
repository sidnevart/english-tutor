from __future__ import annotations

from datetime import date, timedelta

from conftest import TEST_USER

from tutor.practice.models import Section
from tutor.progress.tracker import IssueInput, ProgressTracker


def _issue() -> IssueInput:
    return IssueInput(
        section=Section.WRITING,
        category="grammar",
        skill_code="subject_verb_agreement",
        canonical_key="grammar:subject_verb_agreement",
        original_excerpt="students is",
        correction="students are",
        explanation="A plural subject takes a plural verb.",
        severity=2,
        confidence=0.95,
    )


def test_issue_lifecycle_resolves_after_three_separate_success_dates_and_relapses(repo) -> None:
    tracker = ProgressTracker(repo)
    first = date(2026, 7, 1)

    tracker.record_issue(TEST_USER, _issue(), local_date=first)
    tracker.record_issue(TEST_USER, _issue(), local_date=first + timedelta(days=1))
    assert tracker.issue(TEST_USER, _issue().canonical_key)["state"] == "recurring"

    for offset in (2, 3, 4):
        tracker.record_success(TEST_USER, _issue().canonical_key, first + timedelta(days=offset))
    assert tracker.issue(TEST_USER, _issue().canonical_key)["state"] == "resolved"

    tracker.record_issue(TEST_USER, _issue(), local_date=first + timedelta(days=5))
    assert tracker.issue(TEST_USER, _issue().canonical_key)["state"] == "relapsed"


def test_reading_skill_resolves_after_five_opportunities_at_eighty_percent(repo) -> None:
    tracker = ProgressTracker(repo)
    start = date(2026, 7, 1)

    for offset, success in enumerate((True, True, False, True, True)):
        tracker.record_skill_result(
            TEST_USER,
            Section.READING,
            "inference",
            success,
            local_date=start + timedelta(days=offset),
        )

    stat = tracker.skill_stat(TEST_USER, "inference")
    issue = tracker.issue(TEST_USER, "reading:inference")
    assert stat["opportunities"] == 5
    assert stat["accuracy"] == 0.8
    assert issue["state"] == "resolved"


def test_legacy_session_errors_migrate_once(repo) -> None:
    repo.save_session_errors(
        TEST_USER,
        "write",
        [
            {
                "type": "grammar",
                "error": "students is",
                "correction": "students are",
                "context": "Essay",
            }
        ],
    )
    tracker = ProgressTracker(repo)

    assert tracker.migrate_legacy_errors() == 1
    assert tracker.migrate_legacy_errors() == 0
    assert tracker.issue(TEST_USER, "legacy:grammar:students is") is not None
