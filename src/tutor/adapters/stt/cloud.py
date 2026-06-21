"""Cloud speech-to-text via an OpenAI-compatible transcription API.

Works with Groq (whisper-large-v3) or OpenAI (whisper-1 / gpt-4o-*-transcribe)
through the same OpenAI SDK. Audio is trimmed to the first N seconds with ffmpeg
before upload, which keeps cost down and stays under the API's file-size limit.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from tutor.config import Settings

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class CloudTranscriber:
    def __init__(
        self, api_key: str, base_url: str | None, model: str, max_seconds: int = 720
    ) -> None:
        from openai import AsyncOpenAI

        self.model = model
        self.base_url = base_url
        self._max_seconds = max_seconds
        self._client = (
            AsyncOpenAI(api_key=api_key, base_url=base_url)
            if base_url
            else AsyncOpenAI(api_key=api_key)
        )

    async def transcribe(self, audio_path: Path, lang: str = "en") -> str:
        src = Path(audio_path)
        clip = await self._clip(src)
        try:
            with open(clip, "rb") as f:
                resp = await self._client.audio.transcriptions.create(
                    model=self.model, file=f, language=lang
                )
            return (resp.text or "").strip()
        finally:
            if clip != src and clip.exists():
                clip.unlink(missing_ok=True)

    async def _clip(self, src: Path) -> Path:
        """Trim to the first `max_seconds`, mono 16 kHz, to shrink the upload."""
        if not shutil.which("ffmpeg"):
            return src
        out = src.with_name(f"{src.stem}.clip.mp3")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-t",
            str(self._max_seconds),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return out if proc.returncode == 0 and out.exists() else src


def build_cloud_transcriber(settings: Settings) -> CloudTranscriber:
    if settings.groq_api_key:
        return CloudTranscriber(
            api_key=settings.groq_api_key,
            base_url=_GROQ_BASE_URL,
            model=settings.stt_model or "whisper-large-v3",
            max_seconds=settings.stt_max_seconds,
        )
    if settings.openai_api_key:
        return CloudTranscriber(
            api_key=settings.openai_api_key,
            base_url=None,
            model=settings.stt_model or "whisper-1",
            max_seconds=settings.stt_max_seconds,
        )
    raise RuntimeError("STT_BACKEND=cloud requires GROQ_API_KEY or OPENAI_API_KEY in .env.")
