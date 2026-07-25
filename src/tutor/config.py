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

LLMBackend = Literal["stub", "ollama", "hermes", "mimo", "ollama_mimo"]
STTBackend = Literal["stub", "whisper", "cloud"]
TTSBackend = Literal["stub", "groq", "edge", "openai", "cloud"]
AnkiBackend = Literal["genanki", "ankiconnect", "null"]
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
    anki_backend: AnkiBackend = "genanki"
    notifier_backend: NotifierBackend = "stub"

    # ---- Anki ----
    ankiconnect_url: str = "http://localhost:8765"
    anki_deck: str = "English::Errors"

    # ---- STT/TTS cloud (optional) ----
    groq_api_key: str = ""
    openai_api_key: str = ""
    stt_model: str = ""  # blank -> whisper-large-v3 (Groq) or whisper-1 (OpenAI)
    stt_max_seconds: int = 1800  # transcribe only the first N seconds (cost/size cap)
    tts_model: str = ""  # blank -> canopylabs/orpheus-v1-english (Groq)
    tts_voice: str = "troy"  # Groq Orpheus voice (troy | hannah | austin | ...)

    # ---- Hermes (optional; conversational plane only, never graded path) ----
    hermes_enabled: bool = False
    hermes_home: str = ""
    hermes_base_url: str = ""  # OpenAI-compatible endpoint for conversational turns
    hermes_model: str = ""
    hermes_api_key: str = ""

    # ---- Schedule / paths ----
    tz: str = "Europe/Moscow"
    practice_push_cron: str = "23 19 * * 1,3,5"  # Mon/Wed/Fri 19:23 — bot starts a practice
    weekly_summary_cron: str = "47 10 * * 0"  # Sunday 10:47 — error-trend summary
    db_path: str = "data/tutor.db"
    data_dir: str = "data"
    soul_dir: str = "soul"

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir)

    @property
    def soul_path(self) -> Path:
        return Path(self.soul_dir)

    @property
    def voice_enabled(self) -> bool:
        """Whether the bot should send voice replies (a real TTS backend is set)."""
        return self.tts_backend != "stub"


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings (the single source of configuration)."""
    return Settings()
