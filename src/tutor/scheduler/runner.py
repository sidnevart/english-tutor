"""APScheduler wiring for the focused TOEFL loop."""

from __future__ import annotations

from functools import partial
from zoneinfo import ZoneInfo

from tutor.catalog.replenisher import CatalogReplenisher
from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.eval.rubric import RubricEvaluator
from tutor.interfaces.notifier import Notifier
from tutor.practice.engine import PracticeEngine
from tutor.practice.planner import DailyPlanner
from tutor.scheduler.jobs import (
    expire_attempts,
    push_daily_plan,
    replenish_catalog,
    retry_evaluations,
)


def build_scheduler(
    repo: Repository,
    planner: DailyPlanner,
    notifier: Notifier,
    evaluator: RubricEvaluator,
    settings: Settings,
    user_id: int,
    engine: PracticeEngine | None = None,
    replenisher: CatalogReplenisher | None = None,
):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    tz = ZoneInfo(settings.tz)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        partial(push_daily_plan, repo, planner, notifier, user_id, timezone=settings.tz),
        CronTrigger.from_crontab(settings.practice_push_cron, timezone=tz),
        id="push_daily_plan",
        replace_existing=True,
    )
    scheduler.add_job(
        retry_evaluations,
        "interval",
        minutes=15,
        args=[evaluator],
        id="retry_evaluations",
        replace_existing=True,
    )
    scheduler.add_job(
        expire_attempts,
        "interval",
        minutes=1,
        args=[engine or PracticeEngine(repo), notifier],
        id="expire_attempts",
        replace_existing=True,
    )
    scheduler.add_job(
        replenish_catalog,
        CronTrigger.from_crontab(settings.catalog_replenish_cron, timezone=tz),
        args=[repo, replenisher, settings.catalog_sources, settings.catalog_batch_size, user_id],
        id="replenish_catalog",
        replace_existing=True,
    )
    repo.log_job(
        "scheduler_start",
        "ok",
        f"daily={settings.practice_push_cron} "
        f"catalog={settings.catalog_replenish_cron} tz={settings.tz}",
    )
    return scheduler
