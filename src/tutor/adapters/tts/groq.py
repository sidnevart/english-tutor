"""Groq Orpheus text-to-speech (OpenAI-compatible /audio/speech endpoint).

Requests WAV from Groq, then transcodes to OGG/Opus with ffmpeg so Telegram can
send it as a native voice message. Uses the existing GROQ_API_KEY — one provider
for STT and TTS.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from tutor.config import Settings

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MAX_CHARS = 2000  # keep replies short; Orpheus has input limits


class GroqSynthesizer:
    def __init__(
        self, api_key: str, model: str, voice: str, base_url: str = _GROQ_BASE_URL
    ) -> None:
        self.model = model
        self.voice = voice
        self._api_key = api_key
        self._base_url = base_url

    async def synthesize(self, text: str, out_path: Path) -> Path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wav = out_path.with_suffix(".wav")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/audio/speech",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model,
                    "voice": self.voice,
                    "input": text[:_MAX_CHARS],
                    "response_format": "wav",
                },
            )
            resp.raise_for_status()
            wav.write_bytes(resp.content)

        ogg = out_path if out_path.suffix == ".ogg" else out_path.with_suffix(".ogg")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(wav),
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            str(ogg),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        wav.unlink(missing_ok=True)
        if proc.returncode != 0 or not ogg.exists():
            raise RuntimeError("ffmpeg failed to transcode TTS audio")
        return ogg


def build_groq_synthesizer(settings: Settings) -> GroqSynthesizer:
    if not settings.groq_api_key:
        raise RuntimeError("TTS_BACKEND=groq requires GROQ_API_KEY in .env.")
    return GroqSynthesizer(
        api_key=settings.groq_api_key,
        model=settings.tts_model or "canopylabs/orpheus-v1-english",
        voice=settings.tts_voice or "troy",
    )
