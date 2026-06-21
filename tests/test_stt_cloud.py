"""Cloud STT provider selection (Groq / OpenAI) behind the Transcriber port."""

from __future__ import annotations

import pytest

from tutor.adapters.stt.cloud import _GROQ_BASE_URL, CloudTranscriber, build_cloud_transcriber
from tutor.config import Settings


def test_prefers_groq():
    t = build_cloud_transcriber(Settings(_env_file=None, stt_backend="cloud", groq_api_key="gsk_x"))
    assert isinstance(t, CloudTranscriber)
    assert t.base_url == _GROQ_BASE_URL
    assert t.model == "whisper-large-v3"


def test_openai_when_no_groq():
    t = build_cloud_transcriber(
        Settings(_env_file=None, stt_backend="cloud", openai_api_key="sk-x")
    )
    assert t.base_url is None
    assert t.model == "whisper-1"


def test_model_override():
    t = build_cloud_transcriber(
        Settings(_env_file=None, groq_api_key="gsk_x", stt_model="whisper-large-v3-turbo")
    )
    assert t.model == "whisper-large-v3-turbo"


def test_requires_a_key():
    with pytest.raises(RuntimeError):
        build_cloud_transcriber(Settings(_env_file=None, stt_backend="cloud"))
