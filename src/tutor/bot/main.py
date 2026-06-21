"""Run the Telegram bot (long-polling) with the quiz handlers wired in."""

from __future__ import annotations

import logging

from tutor.adapters.notify.telegram import TelegramNotifier
from tutor.app import open_services
from tutor.bot.handlers import COMMANDS, build_router
from tutor.config import Settings, get_settings
from tutor.scheduler.runner import build_scheduler

log = logging.getLogger("tutor")


async def run_bot(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required to run the bot (see .env).")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import BotCommand

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    with open_services(settings) as svc:
        # Share the polling bot for outbound sends (deliveries, decks, scores).
        svc.notifier = TelegramNotifier(bot)
        dp.include_router(build_router(svc, bot))

        # The slash menu shown when the user types "/".
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])

        scheduler = build_scheduler(svc, settings.admin_user_id)
        scheduler.start()
        me = await bot.get_me()
        log.info(
            "bot @%s polling; scheduler armed (morning '%s', evening '%s' %s)",
            me.username,
            settings.morning_cron,
            settings.evening_cron,
            settings.tz,
        )
        try:
            await dp.start_polling(bot)
        finally:
            scheduler.shutdown(wait=False)
