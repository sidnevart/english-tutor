"""Build and run the APScheduler instance (embedded in the bot, or standalone)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from tutor.config import Settings, get_settings
from tutor.scheduler.jobs import push_practice, weekly_summary

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from tutor.factory import Services


def build_scheduler(
    svc: Services, user_id: int, *, bot: Any = None, storage: Any = None
) -> AsyncIOScheduler:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    if storage is None:
        from aiogram.fsm.storage.memory import MemoryStorage

        storage = MemoryStorage()

    tz = ZoneInfo(svc.settings.tz)
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_job(
        push_practice,
        CronTrigger.from_crontab(svc.settings.practice_push_cron, timezone=tz),
        args=[svc, user_id, bot, storage],
        id="push_practice",
        replace_existing=True,
    )
    scheduler.add_job(
        weekly_summary,
        CronTrigger.from_crontab(svc.settings.weekly_summary_cron, timezone=tz),
        args=[svc, user_id],
        id="weekly_summary",
        replace_existing=True,
    )

    svc.repo.log_job(
        "scheduler_start",
        "ok",
        f"push={svc.settings.practice_push_cron} weekly={svc.settings.weekly_summary_cron} "
        f"tz={svc.settings.tz}",
    )

    return scheduler


async def run_scheduler(settings: Settings | None = None) -> None:
    """Run the scheduler standalone (sends via a Telegram bot, no polling).

    Note: the primary deployment runs the scheduler embedded in the bot
    (`tutor bot`), where push_practice shares the polling bot's FSM storage. In
    standalone mode a fresh MemoryStorage is used — the push still sends its
    message, but the FSM state lives only in this process.
    """
    import asyncio

    from aiogram.fsm.storage.memory import MemoryStorage

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
        scheduler = build_scheduler(svc, settings.admin_user_id, bot=bot, storage=MemoryStorage())
        scheduler.start()
        print("[tutor] scheduler running. Press Ctrl-C to stop.")
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown(wait=False)
