from __future__ import annotations

from datetime import date

from conftest import TEST_USER

from tutor.catalog import BundledCatalog
from tutor.practice.planner import DailyPlanner
from tutor.scheduler.jobs import CATALOG_RESERVE_TARGETS, push_daily_plan, replenish_catalog


class FakeNotifier:
    def __init__(self) -> None:
        self.messages = []

    async def send(self, user_id, text, keyboard=None):
        self.messages.append((user_id, text, keyboard))
        return len(self.messages)


async def test_daily_push_creates_one_plan_and_is_idempotent(repo) -> None:
    notifier = FakeNotifier()
    planner = DailyPlanner(repo, BundledCatalog.load())
    local_day = date(2026, 7, 30)

    first = await push_daily_plan(repo, planner, notifier, TEST_USER, local_date=local_day)
    second = await push_daily_plan(repo, planner, notifier, TEST_USER, local_date=local_day)

    assert first is True
    assert second is False
    assert len(notifier.messages) == 1
    assert "Reading" in notifier.messages[0][1]
    assert "Speaking" in notifier.messages[0][1]
    assert "Writing" in notifier.messages[0][1]
    assert notifier.messages[0][2][0][0][1].startswith("practice:")


def test_scheduler_uses_eight_am_moscow_and_background_jobs(repo):
    from tutor.adapters.llm.stub import StubLLMClient
    from tutor.config import Settings
    from tutor.eval.rubric import RubricEvaluator
    from tutor.progress.tracker import ProgressTracker
    from tutor.scheduler.runner import build_scheduler

    settings = Settings(_env_file=None)
    planner = DailyPlanner(repo, BundledCatalog.load())
    evaluator = RubricEvaluator(repo, StubLLMClient(), ProgressTracker(repo))
    scheduler = build_scheduler(repo, planner, FakeNotifier(), evaluator, settings, TEST_USER)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {
        "push_daily_plan",
        "retry_evaluations",
        "expire_attempts",
        "replenish_catalog",
    }
    assert "hour='8'" in str(jobs["push_daily_plan"].trigger)
    assert str(scheduler.timezone) == "Europe/Moscow"


async def test_replenishment_targets_only_catalog_types_below_reserve(repo) -> None:
    class Builder:
        def __init__(self) -> None:
            self.types = []

        async def build_one(self, source, task_type):
            self.types.append(task_type)
            return object()

    repo.seed_catalog(BundledCatalog.load().tasks)
    builder = Builder()

    await replenish_catalog(
        repo,
        builder,
        ["https://www.nasa.gov/example"],
        batch_size=8,
        user_id=TEST_USER,
    )

    assert builder.types == []
    assert all(
        repo.unseen_catalog_count(TEST_USER, task_type.value) >= target
        for task_type, target in CATALOG_RESERVE_TARGETS.items()
    )
