"""Groq Orpheus TTS adapter selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from tutor.adapters.tts.groq import GroqSynthesizer, build_groq_synthesizer
from tutor.adapters.tts.quality import AudioStats
from tutor.adapters.tts.stub import StubSynthesizer
from tutor.config import Settings
from tutor.factory import build_synthesizer


def test_build_groq_defaults():
    s = build_groq_synthesizer(Settings(_env_file=None, tts_backend="groq", groq_api_key="gsk_x"))
    assert isinstance(s, GroqSynthesizer)
    assert s.model == "canopylabs/orpheus-v1-english"
    assert s.voice == "troy"


def test_build_groq_overrides():
    s = build_groq_synthesizer(
        Settings(_env_file=None, groq_api_key="x", tts_voice="hannah", tts_model="m")
    )
    assert s.voice == "hannah" and s.model == "m"


def test_build_groq_requires_key():
    with pytest.raises(RuntimeError):
        build_groq_synthesizer(Settings(_env_file=None, tts_backend="groq"))


def test_factory_selects_groq_and_stub():
    g = build_synthesizer(Settings(_env_file=None, tts_backend="groq", groq_api_key="x"))
    assert isinstance(g, GroqSynthesizer)
    assert isinstance(
        build_synthesizer(Settings(_env_file=None, tts_backend="stub")), StubSynthesizer
    )


async def test_fragmented_primary_voice_retries_with_austin(tmp_path: Path, monkeypatch) -> None:
    requested_voices: list[str] = []

    class FakeResponse:
        content = b"wav"

        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback) -> None:
            pass

        async def post(self, url, *, headers, json):
            requested_voices.append(json["voice"])
            return FakeResponse()

    stats = iter(
        [
            AudioStats(duration_seconds=3.6, pause_events=24, silence_seconds=2.27),
            AudioStats(duration_seconds=3.2, pause_events=5, silence_seconds=0.65),
        ]
    )

    async def fake_analyze(path: Path) -> AudioStats:
        return next(stats)

    class FakeProcess:
        returncode = 0

        async def wait(self) -> int:
            return 0

    async def fake_subprocess(*args, **kwargs):
        Path(str(args[-1])).write_bytes(b"ogg")
        return FakeProcess()

    monkeypatch.setattr("tutor.adapters.tts.groq.httpx.AsyncClient", FakeClient)
    monkeypatch.setattr("tutor.adapters.tts.groq.analyze_audio", fake_analyze)
    monkeypatch.setattr("tutor.adapters.tts.groq.asyncio.create_subprocess_exec", fake_subprocess)

    output = await GroqSynthesizer("key", "model", "troy").synthesize(
        "The first activity begins near the main entrance.", tmp_path / "prompt.wav"
    )

    assert requested_voices == ["troy", "austin"]
    assert output.read_bytes() == b"ogg"
