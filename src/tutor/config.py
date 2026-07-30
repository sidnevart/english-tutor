"""Typed application configuration.

`config.py` is the ONLY module that reads the environment. Everything else
receives a `Settings` instance. All values default to safe offline stubs, so
the app runs with an empty `.env` (no secrets, no network).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMBackend = Literal["stub", "ollama", "mimo", "ollama_mimo"]
STTBackend = Literal["stub", "whisper", "cloud"]
TTSBackend = Literal["stub", "groq", "edge", "openai", "cloud"]
NotifierBackend = Literal["stub", "telegram"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Telegram bot (learner UX) ----
    bot_token: str = ""
    admin_user_id: int = 764315256

    # ---- Ollama / LLM ----
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "glm-5:cloud"
    ollama_api_key: str = "ollama"

    # ---- MiMo (Anthropic-compatible fallback) ----
    mimo_base_url: str = "https://api.xiaomimimo.com/anthropic"
    mimo_model: str = "mimo-v2.5-pro"
    mimo_api_key: str = ""

    # ---- Adapter selection ----
    llm_backend: LLMBackend = "stub"
    stt_backend: STTBackend = "stub"
    tts_backend: TTSBackend = "stub"
    notifier_backend: NotifierBackend = "stub"

    # ---- STT/TTS cloud (optional) ----
    groq_api_key: str = ""
    openai_api_key: str = ""
    stt_model: str = ""  # blank -> whisper-large-v3 (Groq) or whisper-1 (OpenAI)
    stt_max_seconds: int = 1800  # transcribe only the first N seconds (cost/size cap)
    tts_model: str = ""  # blank -> canopylabs/orpheus-v1-english (Groq)
    tts_voice: str = "troy"  # Groq Orpheus voice (troy | hannah | austin | ...)

    # ---- Schedule / paths ----
    tz: str = "Europe/Moscow"
    practice_push_cron: str = "0 8 * * *"  # Daily 08:00 in the configured timezone
    catalog_replenish_cron: str = "0 4 * * 0"  # Sunday 04:00 — maintain unseen reserve
    catalog_source_urls: str = (
        "https://science.nasa.gov/universe/,"
        "https://oceanservice.noaa.gov/facts/,"
        "https://www.si.edu/spotlight"
    )
    catalog_batch_size: int = 3
    db_path: str = "data/tutor.db"
    data_dir: str = "data"

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def voice_enabled(self) -> bool:
        """Whether the bot should send voice replies (a real TTS backend is set)."""
        return self.tts_backend != "stub"

    @property
    def catalog_sources(self) -> list[str]:
        return [url.strip() for url in self.catalog_source_urls.split(",") if url.strip()]


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings (the single source of configuration)."""
    return Settings()
