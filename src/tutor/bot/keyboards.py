"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard


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


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into (verb, args)."""
    parts = data.split(":")
    return parts[0], parts[1:]
