"""Speech-to-text port (stubbed until a real STT backend is plugged in)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Transcriber(Protocol):
    async def transcribe(self, audio_path: Path, lang: str = "en") -> str: ...
