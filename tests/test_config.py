"""Config loads from .env and exposes typed, parsed values."""

from __future__ import annotations

from tutor.config import Settings


def test_defaults_are_offline_stubs():
    s = Settings(_env_file=None)
    assert s.llm_backend == "stub"
    assert s.notifier_backend == "stub"
    assert s.anki_backend == "genanki"
    assert s.channel_ids == [1137165265, 1356345589]


def test_loads_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "BOT_TOKEN=secret-123\n"
        "LLM_BACKEND=ollama\n"
        "SCRAPE_CHANNELS=10, 20 ,30\n"
        "HERMES_ENABLED=true\n",
        encoding="utf-8",
    )
    s = Settings(_env_file=env)
    assert s.bot_token == "secret-123"
    assert s.llm_backend == "ollama"
    assert s.channel_ids == [10, 20, 30]
    assert s.hermes_enabled is True


def test_blank_api_id_becomes_none(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TG_API_ID=\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert s.tg_api_id is None
