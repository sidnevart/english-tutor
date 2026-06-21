"""Build and run the APScheduler instance (embedded in the bot, or standalone)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from tutor.config import Settings, get_settings
from tutor.scheduler.jobs import (
    daytime_checkin,
    essay_reminder,
    evening_reminder,
    morning_push,
    refresh_content,
    weekly_summary,
)

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from tutor.factory import Services


def build_scheduler(svc: Services, user_id: int) -> AsyncIOScheduler:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    from tutor.domain.enums import DeliveryStatus

    tz = ZoneInfo(svc.settings.tz)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        refresh_content,
        CronTrigger.from_crontab(svc.settings.refresh_cron, timezone=tz),
        args=[svc],
        id="refresh_content",
        replace_existing=True,
    )
    scheduler.add_job(
        morning_push,
        CronTrigger.from_crontab(svc.settings.morning_cron, timezone=tz),
        args=[svc, user_id],
        id="morning_push",
        replace_existing=True,
    )
    scheduler.add_job(
        daytime_checkin,
        CronTrigger.from_crontab(svc.settings.daytime_checkin_cron, timezone=tz),
        args=[svc, user_id],
        id="daytime_checkin",
        replace_existing=True,
    )
    scheduler.add_job(
        evening_reminder,
        CronTrigger.from_crontab(svc.settings.evening_cron, timezone=tz),
        args=[svc, user_id],
        id="evening_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        essay_reminder,
        CronTrigger.from_crontab(svc.settings.essay_cron, timezone=tz),
        args=[svc, user_id],
        id="essay_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        weekly_summary,
        CronTrigger.from_crontab(svc.settings.weekly_summary_cron, timezone=tz),
        args=[svc, user_id],
        id="weekly_summary",
        replace_existing=True,
    )

    # Log scheduler state at startup for diagnostics.
    new_count = svc.repo.count_status(user_id, DeliveryStatus.NEW)
    delivered_count = svc.repo.count_status(user_id, DeliveryStatus.DELIVERED)
    reviewed_count = svc.repo.count_status(user_id, DeliveryStatus.REVIEWED)
    cards = svc.repo.anki_card_count(user_id)
    svc.repo.log_job(
        "scheduler_start", "ok",
        f"content: new={new_count} delivered={delivered_count} reviewed={reviewed_count} "
        f"cards={cards} | crons: refresh={svc.settings.refresh_cron} "
        f"morning={svc.settings.morning_cron} daytime={svc.settings.daytime_checkin_cron} "
        f"evening={svc.settings.evening_cron} essay={svc.settings.essay_cron} "
        f"weekly={svc.settings.weekly_summary_cron} tz={svc.settings.tz}"
    )

    return scheduler


async def run_scheduler(settings: Settings | None = None) -> None:
    """Run the scheduler standalone (sends via a Telegram bot, no polling)."""
    import asyncio

    settings = settings or get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required to run the scheduler (see .env).")

    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from tutor.adapters.notify.telegram import TelegramNotifier
    from tutor.app import open_services

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    with open_services(settings) as svc:
        svc.notifier = TelegramNotifier(bot)
        scheduler = build_scheduler(svc, settings.admin_user_id)
        scheduler.start()
        print("[tutor] scheduler running. Press Ctrl-C to stop.")
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown(wait=False)
