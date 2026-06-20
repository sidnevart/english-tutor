"""Text-to-speech port (stubbed until a real TTS backend is plugged in)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Synthesizer(Protocol):
    async def synthesize(self, text: str, out_path: Path) -> Path: ...
