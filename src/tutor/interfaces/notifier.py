"""Outbound messaging port. The stub records messages; the real impl talks to
the Telegram Bot API. Keyboards are expressed structurally so the port never
depends on aiogram."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

# Rows of (label, callback_data) inline buttons.
Keyboard = list[list[tuple[str, str]]]


class Notifier(Protocol):
    async def send(self, user_id: int, text: str, keyboard: Keyboard | None = None) -> int:
        """Send a text message; returns the message id."""
        ...

    async def send_file(self, user_id: int, path: Path, caption: str = "") -> int: ...
