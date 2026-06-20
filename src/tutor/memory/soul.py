"""Load the SOUL.md persona (the tutor's durable identity)."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SOUL = (
    "You are a patient, encouraging TOEFL preparation coach. Write rigorous "
    "multiple-choice questions, explain answers briefly, and reinforce "
    "previously-studied vocabulary when it fits naturally."
)


def load_soul(soul_dir: str | Path) -> str:
    """Return the SOUL.md persona text, or a built-in default if absent/empty."""
    path = Path(soul_dir) / "SOUL.md"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return DEFAULT_SOUL
