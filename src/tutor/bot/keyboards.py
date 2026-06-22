"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard

_LETTERS = "ABCDEFGH"


def quiz_invite(content_id: int, label: str = "📖 Quiz me") -> Keyboard:
    return [[(label, f"quiz:{content_id}")]]


def evening_actions(content_id: int | None) -> Keyboard:
    """Evening buttons: discuss today's top item + open-ended speaking practice."""
    rows: Keyboard = []
    if content_id is not None:
        rows.append([("💬 Discuss today's material", f"discuss:{content_id}")])
    rows.append([("🎙 Speaking practice", "speak:start")])
    return rows


def reset_confirm() -> Keyboard:
    """Confirmation keyboard for the /reset command."""
    return [
        [("✅ Yes, reset everything", "reset:confirm")],
        [("❌ Cancel", "reset:cancel")],
    ]


def answer_options(content_id: int, question_id: int, options: list[str]) -> Keyboard:
    """Compact letter buttons (A/B/C/D) in rows of four. The option *text* lives
    in the message body, so nothing gets truncated on the button."""
    buttons = [(_LETTERS[i], f"ans:{content_id}:{question_id}:{i}") for i in range(len(options))]
    return [buttons[i : i + 4] for i in range(0, len(buttons), 4)]


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into (verb, args)."""
    parts = data.split(":")
    return parts[0], parts[1:]
