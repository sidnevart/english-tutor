from __future__ import annotations

from datetime import date, timedelta

from conftest import TEST_USER

from tutor.catalog import BundledCatalog
from tutor.practice.models import Section, TaskType
from tutor.practice.planner import DailyPlanner


def test_first_plan_has_all_sections_and_is_idempotent(repo) -> None:
    planner = DailyPlanner(repo, BundledCatalog.load())
    today = date(2026, 7, 30)

    first = planner.ensure_plan(TEST_USER, today)
    second = planner.ensure_plan(TEST_USER, today)

    assert first == second
    assert [entry.section for entry in first.entries] == [
        Section.READING,
        Section.SPEAKING,
        Section.WRITING,
    ]
    assert [entry.task_type for entry in first.entries] == [
        TaskType.COMPLETE_WORDS,
        TaskType.LISTEN_REPEAT,
        TaskType.BUILD_SENTENCE,
    ]


def test_writing_uses_calendar_cadence_and_skipped_days_do_not_shift_it(repo) -> None:
    planner = DailyPlanner(repo, BundledCatalog.load())
    anchor = date(2026, 7, 30)
    planner.ensure_plan(TEST_USER, anchor)

    day_one = planner.ensure_plan(TEST_USER, anchor + timedelta(days=1))
    day_four = planner.ensure_plan(TEST_USER, anchor + timedelta(days=4))

    assert day_one.entry(Section.WRITING) is None
    assert day_four.entry(Section.WRITING) is not None
    assert day_four.entry(Section.WRITING).task_type is TaskType.EMAIL


def test_sixty_day_plan_rotation_does_not_repeat_tasks(repo) -> None:
    planner = DailyPlanner(repo, BundledCatalog.load())
    anchor = date(2026, 1, 1)
    plans = [
        planner.ensure_plan(TEST_USER, anchor + timedelta(days=offset)) for offset in range(60)
    ]

    reading_ids = [plan.entry(Section.READING).task_id for plan in plans]
    speaking_ids = [plan.entry(Section.SPEAKING).task_id for plan in plans]
    writing_ids = [
        plan.entry(Section.WRITING).task_id for plan in plans if plan.entry(Section.WRITING)
    ]
    assert len(reading_ids) == len(set(reading_ids)) == 60
    assert len(speaking_ids) == len(set(speaking_ids)) == 60
    assert len(writing_ids) == len(set(writing_ids)) == 30


def test_generated_catalog_task_enters_rotation_before_a_repeat(repo) -> None:
    catalog = BundledCatalog.load()
    planner = DailyPlanner(repo, catalog)
    extra = next(
        task for task in catalog.tasks if task.task_type is TaskType.COMPLETE_WORDS
    ).model_copy(
        update={
            "id": "generated-complete-words",
            "provenance": "source-backed-original",
        }
    )
    repo.seed_catalog([extra])
    anchor = date(2026, 1, 1)

    plans = [
        planner.ensure_plan(TEST_USER, anchor + timedelta(days=offset)) for offset in range(61)
    ]

    assert plans[-1].entry(Section.READING).task_id == "generated-complete-words"


def test_partial_plan_is_repaired_after_restart(repo) -> None:
    catalog = BundledCatalog.load()
    planner = DailyPlanner(repo, catalog)
    day = date(2026, 7, 30)
    reading = catalog.select(Section.READING, TaskType.COMPLETE_WORDS)
    repo.insert_plan_entry(TEST_USER, day.isoformat(), Section.READING.value, reading.id)

    repaired = planner.ensure_plan(TEST_USER, day)

    assert {entry.section for entry in repaired.entries} == set(Section)
