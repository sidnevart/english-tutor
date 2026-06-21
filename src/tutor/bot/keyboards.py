"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard

_LETTERS = "ABCDEFGH"


def quiz_invite(content_id: int) -> Keyboard:
    return [[("📖 Quiz me", f"quiz:{content_id}")]]


def answer_options(content_id: int, question_id: int, options: list[str]) -> Keyboard:
    """Compact letter buttons (A/B/C/D) in rows of four. The option *text* lives
    in the message body, so nothing gets truncated on the button."""
    buttons = [(_LETTERS[i], f"ans:{content_id}:{question_id}:{i}") for i in range(len(options))]
    return [buttons[i : i + 4] for i in range(0, len(buttons), 4)]


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into (verb, args)."""
    parts = data.split(":")
    return parts[0], parts[1:]
