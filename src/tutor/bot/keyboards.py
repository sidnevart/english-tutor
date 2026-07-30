"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard


def reset_confirm() -> Keyboard:
    """Confirmation keyboard for the /reset command."""
    return [
        [("✅ Yes, erase my progress", "reset:confirm")],
        [("❌ Cancel", "reset:cancel")],
    ]


def parse_callback(data: str) -> tuple[str, list[str]]:
    """Split callback data into (verb, args)."""
    parts = data.split(":")
    return parts[0], parts[1:]
