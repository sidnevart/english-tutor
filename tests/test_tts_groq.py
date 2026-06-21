"""Groq Orpheus TTS adapter selection."""

from __future__ import annotations

import pytest

from tutor.adapters.tts.groq import GroqSynthesizer, build_groq_synthesizer
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
