"""Build and run the APScheduler instance (embedded in the bot, or standalone)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from tutor.config import Settings, get_settings
from tutor.scheduler.jobs import evening_reminder, morning_push, refresh_content

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from tutor.factory import Services


def build_scheduler(svc: Services, user_id: int) -> AsyncIOScheduler:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

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
        evening_reminder,
        CronTrigger.from_crontab(svc.settings.evening_cron, timezone=tz),
        args=[svc, user_id],
        id="evening_reminder",
        replace_existing=True,
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
