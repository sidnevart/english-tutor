"""Offline TTS stub — writes an empty marker file, no model, no network."""

from __future__ import annotations

from pathlib import Path


class StubSynthesizer:
    async def synthesize(self, text: str, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")
        return out_path
