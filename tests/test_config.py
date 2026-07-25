"""Config loads from .env and exposes typed, parsed values."""

from __future__ import annotations

from tutor.config import Settings


def test_defaults_are_offline_stubs():
    s = Settings(_env_file=None)
    assert s.llm_backend == "stub"
    assert s.notifier_backend == "stub"
    assert s.anki_backend == "genanki"
    assert s.anki_deck == "English::Errors"
    assert s.practice_push_cron == "23 19 * * 1,3,5"


def test_loads_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "BOT_TOKEN=secret-123\nLLM_BACKEND=ollama\nHERMES_ENABLED=true\n",
        encoding="utf-8",
    )
    s = Settings(_env_file=env)
    assert s.bot_token == "secret-123"
    assert s.llm_backend == "ollama"
    assert s.hermes_enabled is True
