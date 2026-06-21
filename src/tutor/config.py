"""Typed application configuration.

`config.py` is the ONLY module that reads the environment. Everything else
receives a `Settings` instance. All values default to safe offline stubs, so
the app runs with an empty `.env` (no secrets, no network).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMBackend = Literal["stub", "ollama", "hermes"]
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

    # ---- Telegram userbot (scraping) ----
    tg_api_id: int | None = None
    tg_api_hash: str = ""
    tg_session_string: str = ""
    tg_session_path: str = "bot_data/telegram_e2e_session"
    scrape_channels: str = "1137165265,1356345589"
    min_article_len: int = 350  # drop blurbs/ads shorter than this when scraping

    # ---- Ollama / LLM ----
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "glm-5:cloud"
    ollama_api_key: str = "ollama"

    # ---- Adapter selection ----
    llm_backend: LLMBackend = "stub"
    stt_backend: STTBackend = "stub"
    tts_backend: TTSBackend = "stub"
    anki_backend: AnkiBackend = "genanki"
    notifier_backend: NotifierBackend = "stub"

    # ---- Anki ----
    ankiconnect_url: str = "http://localhost:8765"
    anki_deck: str = "TOEFL::Daily"

    # ---- STT/TTS cloud (optional) ----
    groq_api_key: str = ""
    openai_api_key: str = ""
    stt_model: str = ""  # blank -> whisper-large-v3 (Groq) or whisper-1 (OpenAI)
    stt_max_seconds: int = 720  # transcribe only the first N seconds (cost/size cap)
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
    refresh_cron: str = "0 7 * * *"  # scrape channels + ingest podcasts (before morning push)
    morning_cron: str = "30 7 * * *"
    evening_cron: str = "0 20 * * *"
    morning_articles: int = 2  # how many articles to deliver each morning
    morning_podcasts: int = 2  # how many podcasts to deliver each morning
    flashcards_per_item: int = 8  # words+idioms Anki cards generated per delivered item
    db_path: str = "data/tutor.db"
    data_dir: str = "data"
    soul_dir: str = "soul"

    @field_validator("tg_api_id", mode="before")
    @classmethod
    def _blank_int_to_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @property
    def channel_ids(self) -> list[int]:
        return [int(c.strip()) for c in self.scrape_channels.split(",") if c.strip()]

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
