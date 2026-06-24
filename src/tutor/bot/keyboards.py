"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard

_LETTERS = "ABCDEFGH"


def evening_actions(content_id: int | None) -> Keyboard:
    """Evening buttons: discuss today's top item + open-ended speaking.

    Comprehension practice now happens through the task file delivered with each
    item, so there is no inline quiz button here.
    """
    rows: Keyboard = []
    if content_id is not None:
        rows.append([("💬 Discuss today's material", f"discuss:{content_id}")])
    rows.append([("🎙 Speaking practice", "speak:start")])
    return rows


def speaking_menu() -> Keyboard:
    """Pick one of the four official TOEFL Speaking task types."""
    return [
        [("1 · Independent", "spk:task:independent")],
        [("2 · Campus (read+listen)", "spk:task:campus")],
        [("3 · Concept (read+listen)", "spk:task:concept")],
        [("4 · Lecture (listen)", "spk:task:lecture")],
    ]


def reset_confirm() -> Keyboard:
    """Confirmation keyboard for the /reset command."""
    return [
        [("✅ Yes, reset everything", "reset:confirm")],
        [("❌ Cancel", "reset:cancel")],
    ]


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into (verb, args)."""
    parts = data.split(":")
    return parts[0], parts[1:]
