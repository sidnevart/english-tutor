"""Offline STT stub — returns placeholder text, no model, no network."""

from __future__ import annotations

from pathlib import Path


class StubTranscriber:
    async def transcribe(self, audio_path: Path, lang: str = "en") -> str:
        return f"[stub transcript of {Path(audio_path).name}]"
