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

LLMBackend = Literal["stub", "ollama", "hermes", "mimo"]
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
    max_article_len: int = 4500  # ~700-900 words; TOEFL-passage scale (honest read time)
    scrape_daily_limit: int = 50  # new messages to check per channel per daily run
    scrape_history_batch: int = 200  # historical messages to backfill per channel per run
    pdf_max_size_mb: int = 100  # max PDF size to download (MB)
    pdf_articles_per_issue: int = 10  # max articles to extract per PDF

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
    anki_deck: str = "TOEFL::Daily"

    # ---- STT/TTS cloud (optional) ----
    groq_api_key: str = ""
    openai_api_key: str = ""
    guardian_api_key: str = "test"  # free dev key; register at open-platform.theguardian.com
    stt_model: str = ""  # blank -> whisper-large-v3 (Groq) or whisper-1 (OpenAI)
    stt_max_seconds: int = 1800  # transcribe only the first N seconds (cost/size cap)
    max_podcast_segment_min: int = 25  # split episodes longer than this into daily segments
    max_ingest_duration_min: int = 40  # skip episodes longer than this at ingest time
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
    morning_cron: str = "0 8 * * *"
    evening_cron: str = "0 20 * * *"
    daytime_checkin_cron: str = "0 13 * * *"  # mid-day check-in (praise + nudge)
    morning_articles: int = 2  # how many articles to deliver each morning
    morning_podcasts: int = 2  # how many podcasts to deliver each morning
    essay_cron: str = "0 18 * * 3,6"  # weekly essay reminder (Wed + Sat at 18:00)
    weekly_summary_cron: str = "0 19 * * 0"  # weekly summary (Sunday at 19:00)
    flashcards_per_item: int = 0  # Anki cards per delivered item; 0 = unlimited (exhaustive)
    reading_questions: int = 10  # TOEFL iBT reading-set size (legacy per-item interactive)
    listening_questions: int = 6  # TOEFL iBT listening-set size (legacy per-item interactive)
    reading_questions_per_item: int = 4  # questions per article in the daily file
    listening_questions_per_item: int = 4  # questions per podcast in the daily file
    reading_time_min: int = 18  # recommended soft time limit for a reading set (minutes)
    listening_time_min: int = 7  # recommended soft time limit for a listening set (minutes)
    speaking_grace_sec: int = 6  # head start before the speaking prep timer starts
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
