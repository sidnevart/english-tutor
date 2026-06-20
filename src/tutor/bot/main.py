"""Run the Telegram bot (long-polling) with the quiz handlers wired in."""

from __future__ import annotations

from tutor.adapters.notify.telegram import TelegramNotifier
from tutor.app import open_services
from tutor.bot.handlers import build_router
from tutor.config import Settings, get_settings
from tutor.scheduler.runner import build_scheduler


async def run_bot(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required to run the bot (see .env).")

    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    with open_services(settings) as svc:
        # Share the polling bot for outbound sends (deliveries, decks, scores).
        svc.notifier = TelegramNotifier(bot)
        dp.include_router(build_router(svc, bot))

        scheduler = build_scheduler(svc, settings.admin_user_id)
        scheduler.start()
        me = await bot.get_me()
        print(
            f"[tutor] bot @{me.username} is polling; scheduler armed "
            f"(morning '{settings.morning_cron}', evening '{settings.evening_cron}' "
            f"{settings.tz}). Press Ctrl-C to stop."
        )
        try:
            await dp.start_polling(bot)
        finally:
            scheduler.shutdown(wait=False)
