"""Pure inline-keyboard builders (structural; no aiogram dependency).

Callback data uses a compact ``verb:args`` scheme parsed by `parse_callback`.
"""

from __future__ import annotations

from tutor.interfaces.notifier import Keyboard

_LETTERS = "ABCDEFGH"


def evening_actions(content_id: int | None) -> Keyboard:
    """Evening buttons: quiz + discuss today's top item + open-ended speaking."""
    rows: Keyboard = []
    if content_id is not None:
        rows.append([("📖 Quiz me", f"quiz:start:{content_id}")])
        rows.append([("💬 Discuss today's material", f"discuss:{content_id}")])
    rows.append([("🎙 Speaking practice", "speak:start")])
    return rows


def quiz_start(content_id: int) -> Keyboard:
    """Single button attached to a delivered item to launch its comprehension quiz."""
    return [[("📖 Start quiz", f"quiz:start:{content_id}")]]


def quiz_options(n: int, *, multi: bool = False, selected: list[int] | None = None) -> Keyboard:
    """Letter buttons (A, B, …) for the current question, 4 per row.

    For multi-select, selected options are marked with a ✓ and a Submit row is
    appended. Callback data carries only the option index; the active question is
    tracked in FSM state.
    """
    selected = selected or []
    buttons: list[tuple[str, str]] = []
    for i in range(n):
        letter = _LETTERS[i] if i < len(_LETTERS) else str(i + 1)
        label = f"✅ {letter}" if (multi and i in selected) else letter
        buttons.append((label, f"quiz:opt:{i}"))
    rows: Keyboard = [buttons[j : j + 4] for j in range(0, len(buttons), 4)]
    if multi:
        rows.append([("✅ Submit answer", "quiz:submit")])
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
