from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import TEST_USER

from tutor.catalog import BundledCatalog
from tutor.practice.engine import ActivePracticeError, PracticeEngine
from tutor.practice.models import Section, TaskType
from tutor.practice.planner import DailyPlanner
from tutor.progress.tracker import ProgressTracker


def _plans(repo):
    planner = DailyPlanner(repo, BundledCatalog.load())
    anchor = date(2026, 7, 30)
    return [planner.ensure_plan(TEST_USER, anchor + timedelta(days=i)) for i in range(6)]


def test_engine_starts_and_resumes_exact_durable_item(repo) -> None:
    plan = _plans(repo)[0]
    engine = PracticeEngine(repo)
    entry = plan.entry(Section.SPEAKING)

    attempt = engine.start(TEST_USER, entry.id, now=datetime(2026, 7, 30, tzinfo=UTC))
    engine.submit_current(TEST_USER, entry.payload["sentences"][0])
    engine.cancel(TEST_USER)
    resumed = engine.start(TEST_USER, entry.id)

    assert attempt.id == resumed.id
    assert resumed.current_item == 1
    assert resumed.status == "active"


def test_only_one_practice_can_be_active(repo) -> None:
    plan = _plans(repo)[0]
    engine = PracticeEngine(repo)
    engine.start(TEST_USER, plan.entry(Section.READING).id)

    with pytest.raises(ActivePracticeError):
        engine.start(TEST_USER, plan.entry(Section.SPEAKING).id)


@pytest.mark.parametrize(
    ("task_type", "response_factory", "expected_max"),
    [
        (TaskType.COMPLETE_WORDS, lambda p, i: " ".join(p["answers"]), 10.0),
        (TaskType.DAILY_LIFE, lambda p, i: str(p["questions"][i]["correct"]), 3.0),
        (TaskType.ACADEMIC_PASSAGE, lambda p, i: str(p["questions"][i]["correct"]), 5.0),
        (TaskType.LISTEN_REPEAT, lambda p, i: p["sentences"][i], 35.0),
        (TaskType.INTERVIEW, lambda p, i: "A relevant developed spoken response.", 20.0),
        (TaskType.BUILD_SENTENCE, lambda p, i: p["items"][i]["answer"], 10.0),
        (
            TaskType.EMAIL,
            lambda p, i: "Dear Coordinator, I am writing to request help. Thank you.",
            5.0,
        ),
        (
            TaskType.ACADEMIC_DISCUSSION,
            lambda p, i: "I agree with Leah because long-term evidence matters.",
            5.0,
        ),
    ],
)
def test_all_eight_task_types_complete(repo, task_type, response_factory, expected_max) -> None:
    plans = _plans(repo)
    entries = [entry for plan in plans for entry in plan.entries]
    entry = next(entry for entry in entries if entry.task_type is task_type)
    engine = PracticeEngine(repo)
    attempt = engine.start(TEST_USER, entry.id)

    while attempt.status == "active":
        attempt = engine.submit_current(
            TEST_USER, response_factory(entry.payload, attempt.current_item)
        )

    assert attempt.status == "completed"
    assert attempt.max_score == expected_max
    if task_type in {TaskType.INTERVIEW, TaskType.EMAIL, TaskType.ACADEMIC_DISCUSSION}:
        assert attempt.evaluation_state == "pending"
    else:
        assert attempt.raw_score == expected_max


def test_duplicate_submission_is_idempotent(repo) -> None:
    entry = _plans(repo)[0].entry(Section.READING)
    engine = PracticeEngine(repo)
    attempt = engine.start(TEST_USER, entry.id)
    response = " ".join(entry.payload["answers"])

    first = engine.submit(TEST_USER, attempt.id, 0, response)
    second = engine.submit(TEST_USER, attempt.id, 0, response)

    assert first == second
    assert repo.attempt_item_count(attempt.id) == 1


def test_deterministic_reading_answer_updates_skill_profile(repo) -> None:
    entry = _plans(repo)[1].entry(Section.READING)
    assert entry.task_type is TaskType.DAILY_LIFE
    tracker = ProgressTracker(repo)
    engine = PracticeEngine(repo, tracker)
    engine.start(TEST_USER, entry.id)

    engine.submit_current(TEST_USER, "99")

    stat = tracker.skill_stat(TEST_USER, entry.payload["questions"][0]["skill"])
    assert stat["opportunities"] == 1
    assert stat["successes"] == 0


def test_email_and_discussion_receive_real_deadlines(repo) -> None:
    entries = [entry for plan in _plans(repo) for entry in plan.entries]
    engine = PracticeEngine(repo)
    now = datetime(2026, 7, 30, 5, 0, tzinfo=UTC)
    for task_type, minutes in ((TaskType.EMAIL, 7), (TaskType.ACADEMIC_DISCUSSION, 10)):
        entry = next(e for e in entries if e.task_type is task_type)
        attempt = engine.start(TEST_USER, entry.id, now=now)
        assert attempt.deadline_at == now + timedelta(minutes=minutes)
        engine.cancel(TEST_USER)


def test_interview_timer_starts_only_after_prompt_delivery(repo) -> None:
    entries = [entry for plan in _plans(repo) for entry in plan.entries]
    entry = next(e for e in entries if e.task_type is TaskType.INTERVIEW)
    engine = PracticeEngine(repo)
    delivered_at = datetime(2026, 7, 30, 5, 0, tzinfo=UTC)

    attempt = engine.start(TEST_USER, entry.id, now=delivered_at - timedelta(seconds=20))
    armed = engine.arm_interview_deadline(
        TEST_USER, attempt.id, attempt.current_item, now=delivered_at
    )

    assert attempt.deadline_at is None
    assert armed.deadline_at == delivered_at + timedelta(seconds=45)


def test_late_email_is_closed_as_incomplete(repo) -> None:
    entries = [entry for plan in _plans(repo) for entry in plan.entries]
    entry = next(e for e in entries if e.task_type is TaskType.EMAIL)
    engine = PracticeEngine(repo)
    now = datetime(2026, 7, 30, 5, 0, tzinfo=UTC)
    engine.start(TEST_USER, entry.id, now=now)

    expired = engine.submit_current(
        TEST_USER, "This arrived too late.", now=now + timedelta(minutes=8)
    )

    assert expired.status == "completed"
    assert expired.raw_score == 0
    assert expired.evaluation_state == "complete"


def test_completed_plan_cannot_be_started_again(repo) -> None:
    entry = _plans(repo)[0].entry(Section.READING)
    engine = PracticeEngine(repo)
    engine.start(TEST_USER, entry.id)
    engine.submit_current(TEST_USER, " ".join(entry.payload["answers"]))

    with pytest.raises(ActivePracticeError):
        engine.start(TEST_USER, entry.id)


def test_build_sentence_draft_is_cleared_between_items(repo) -> None:
    entries = [entry for plan in _plans(repo) for entry in plan.entries]
    entry = next(e for e in entries if e.task_type is TaskType.BUILD_SENTENCE)
    engine = PracticeEngine(repo)
    attempt = engine.start(TEST_USER, entry.id)
    repo.append_attempt_draft(attempt.id, 0)

    next_item = engine.submit_current(TEST_USER, entry.payload["items"][0]["answer"])

    assert next_item.current_item == 1
    assert repo.attempt_draft(attempt.id) == []


def test_speaking_metrics_are_persisted(repo) -> None:
    entry = _plans(repo)[0].entry(Section.SPEAKING)
    engine = PracticeEngine(repo)
    attempt = engine.start(TEST_USER, entry.id)

    engine.submit_current(
        TEST_USER,
        entry.payload["sentences"][0],
        metrics={"duration_seconds": 3.2, "words_per_minute": 112.5},
    )

    import json

    metrics = json.loads(repo.attempt_items(attempt.id)[0]["metrics_json"])
    assert metrics["duration_seconds"] == 3.2


def test_paused_attempt_rejects_stale_answer(repo) -> None:
    entry = _plans(repo)[1].entry(Section.READING)
    engine = PracticeEngine(repo)
    attempt = engine.start(TEST_USER, entry.id)
    engine.cancel(TEST_USER)

    with pytest.raises(ActivePracticeError):
        engine.submit(TEST_USER, attempt.id, 0, "@0")


def test_answer_and_progress_update_are_atomic(repo) -> None:
    class BrokenTracker:
        def record_skill_result(self, *args, **kwargs):
            raise RuntimeError("profile write failed")

    entry = _plans(repo)[1].entry(Section.READING)
    engine = PracticeEngine(repo, BrokenTracker())
    attempt = engine.start(TEST_USER, entry.id)

    with pytest.raises(RuntimeError, match="profile write failed"):
        engine.submit_current(TEST_USER, "@0")

    assert repo.attempt_item_count(attempt.id) == 0
    assert engine.get_attempt(attempt.id).current_item == 0
