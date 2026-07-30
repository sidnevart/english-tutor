"""Idempotent daily delivery and background maintenance jobs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from tutor.bot.views import render_plan
from tutor.catalog.replenisher import CatalogReplenisher
from tutor.db.repository import Repository
from tutor.eval.rubric import RubricEvaluator
from tutor.interfaces.notifier import Notifier
from tutor.practice.engine import PracticeEngine
from tutor.practice.models import TaskType
from tutor.practice.planner import DailyPlanner

CATALOG_RESERVE_TARGETS = {
    TaskType.COMPLETE_WORDS: 5,
    TaskType.DAILY_LIFE: 5,
    TaskType.ACADEMIC_PASSAGE: 5,
    TaskType.LISTEN_REPEAT: 7,
    TaskType.INTERVIEW: 7,
    TaskType.BUILD_SENTENCE: 3,
    TaskType.EMAIL: 3,
    TaskType.ACADEMIC_DISCUSSION: 3,
}


async def push_daily_plan(
    repo: Repository,
    planner: DailyPlanner,
    notifier: Notifier,
    user_id: int,
    *,
    local_date: date | None = None,
    timezone: str = "Europe/Moscow",
) -> bool:
    local_date = local_date or datetime.now(ZoneInfo(timezone)).date()
    plan = planner.ensure_plan(user_id, local_date)
    if repo.plan_notified(user_id, local_date.isoformat()):
        repo.log_job("push_daily_plan", "skipped", local_date.isoformat())
        return False
    text, keyboard = render_plan(plan)
    await notifier.send(user_id, text, keyboard)
    repo.mark_plan_notified(user_id, local_date.isoformat())
    repo.log_job("push_daily_plan", "ok", local_date.isoformat())
    return True


async def retry_evaluations(evaluator: RubricEvaluator) -> None:
    completed = await evaluator.retry_pending()
    evaluator.repo.log_job("retry_evaluations", "ok", f"completed={completed}")


async def expire_attempts(engine: PracticeEngine, notifier: Notifier) -> None:
    attempts = engine.expire_overdue()
    for attempt in attempts:
        await notifier.send(
            attempt.user_id,
            "⏱ The writing deadline passed. The block was saved as incomplete; "
            "open /today to continue.",
        )
    engine.repo.log_job("expire_attempts", "ok", f"expired={len(attempts)}")


async def replenish_catalog(
    repo: Repository,
    builder: CatalogReplenisher | None = None,
    source_urls: list[str] | None = None,
    batch_size: int = 3,
    user_id: int = 0,
) -> None:
    if builder is None or not source_urls:
        repo.log_job("replenish_catalog", "skipped", "no builder or sources configured")
        return
    deficits = [
        task_type
        for task_type, target in CATALOG_RESERVE_TARGETS.items()
        for _ in range(max(0, target - repo.unseen_catalog_count(user_id, task_type.value)))
    ]
    if not deficits:
        repo.log_job("replenish_catalog", "skipped", "14-day unseen reserve is full")
        return
    week = datetime.now(UTC).isocalendar().week
    accepted = 0
    attempted = min(batch_size, len(deficits))
    for offset, task_type in enumerate(deficits[:attempted]):
        source = source_urls[(week + offset) % len(source_urls)]
        if await builder.build_one(source, task_type) is not None:
            accepted += 1
    repo.log_job("replenish_catalog", "ok", f"accepted={accepted}/{attempted}")
