"""Real notifier over the Telegram Bot API (aiogram).

Takes an injected bot object so the conversion logic is unit-testable without a
network client. The factory builds the concrete `aiogram.Bot`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from tutor.interfaces.notifier import Keyboard


def to_markup(keyboard: Keyboard) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
            for row in keyboard
        ]
    )


class _BotLike(Protocol):
    async def send_message(self, chat_id: int, text: str, **kwargs: object) -> object: ...
    async def send_document(self, chat_id: int, document: object, **kwargs: object) -> object: ...


class TelegramNotifier:
    def __init__(self, bot: _BotLike) -> None:
        self._bot = bot

    async def send(self, user_id: int, text: str, keyboard: Keyboard | None = None) -> int:
        markup = to_markup(keyboard) if keyboard else None
        msg = await self._bot.send_message(user_id, text, reply_markup=markup)
        return int(msg.message_id)  # type: ignore[attr-defined]

    async def send_file(self, user_id: int, path: Path, caption: str = "") -> int:
        msg = await self._bot.send_document(
            user_id, FSInputFile(str(path)), caption=caption or None
        )
        return int(msg.message_id)  # type: ignore[attr-defined]
