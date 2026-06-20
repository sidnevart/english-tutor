"""Adapter selection. The ONLY place that maps config -> concrete impl.

Reals are imported lazily so the offline stub path never imports network
clients, and backends that arrive in a later milestone fail with a clear
message instead of an ImportError.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.interfaces import AnkiSink, LLMClient, Notifier, Synthesizer, Transcriber


def build_llm(settings: Settings) -> LLMClient:
    match settings.llm_backend:
        case "ollama":
            from tutor.adapters.llm.ollama import OllamaLLMClient

            return OllamaLLMClient(
                settings.ollama_base_url, settings.ollama_api_key, settings.ollama_model
            )
        case "hermes":
            from tutor.adapters.llm.hermes import build_hermes_client

            return build_hermes_client(settings)
        case _:
            from tutor.adapters.llm.stub import StubLLMClient

            return StubLLMClient()


def build_notifier(settings: Settings) -> Notifier:
    if settings.notifier_backend == "telegram":
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        from tutor.adapters.notify.telegram import TelegramNotifier

        bot = Bot(
            settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        return TelegramNotifier(bot)
    from tutor.adapters.notify.stub import StubNotifier

    return StubNotifier()


def build_anki(settings: Settings) -> AnkiSink:
    match settings.anki_backend:
        case "ankiconnect":
            from tutor.adapters.anki.ankiconnect import AnkiConnectSink

            return AnkiConnectSink(settings.ankiconnect_url)
        case "null":
            from tutor.adapters.anki.null import NullSink

            return NullSink()
        case _:
            from tutor.adapters.anki.genanki_sink import GenankiSink

            return GenankiSink(settings.data_path)


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.stt_backend in ("whisper", "cloud"):
        try:
            from tutor.adapters.stt.real import build_real_transcriber
        except ImportError as exc:  # arrives in M6
            raise RuntimeError(
                f"STT_BACKEND={settings.stt_backend} not available yet (M6)."
            ) from exc
        return build_real_transcriber(settings)
    from tutor.adapters.stt.stub import StubTranscriber

    return StubTranscriber()


def build_synthesizer(settings: Settings) -> Synthesizer:
    if settings.tts_backend in ("edge", "cloud"):
        try:
            from tutor.adapters.tts.real import build_real_synthesizer
        except ImportError as exc:  # arrives later
            raise RuntimeError(f"TTS_BACKEND={settings.tts_backend} not available yet.") from exc
        return build_real_synthesizer(settings)
    from tutor.adapters.tts.stub import StubSynthesizer

    return StubSynthesizer()


@dataclass
class Services:
    """Everything the pipeline needs, with concrete adapters resolved."""

    settings: Settings
    repo: Repository
    llm: LLMClient
    notifier: Notifier
    anki: AnkiSink
    transcriber: Transcriber
    synthesizer: Synthesizer


def build_services(settings: Settings, conn: sqlite3.Connection) -> Services:
    return Services(
        settings=settings,
        repo=Repository(conn),
        llm=build_llm(settings),
        notifier=build_notifier(settings),
        anki=build_anki(settings),
        transcriber=build_transcriber(settings),
        synthesizer=build_synthesizer(settings),
    )
