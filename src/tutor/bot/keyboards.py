"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard

_LETTERS = "ABCDEFGH"
_MAX_BTN = 64  # Telegram inline button text is capped; keep it short


def quiz_invite(content_id: int) -> Keyboard:
    return [[("📖 Quiz me", f"quiz:{content_id}")]]


def answer_options(question_id: int, options: list[str]) -> Keyboard:
    return [
        [(f"{_LETTERS[i]}. {opt}"[:_MAX_BTN], f"ans:{question_id}:{i}")]
        for i, opt in enumerate(options)
    ]


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into (verb, args)."""
    parts = data.split(":")
    return parts[0], parts[1:]
