"""Adapter selection. The ONLY place that maps config -> concrete impl.

Reals are imported lazily so the offline stub path never imports network
clients, and backends that arrive in a later milestone fail with a clear
message instead of an ImportError.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from tutor.adapters.tts.cues import AudioCueComposer
from tutor.catalog import BundledCatalog
from tutor.catalog.replenisher import CatalogReplenisher, HttpSourceFetcher
from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.eval.email import StandaloneEmailChecker
from tutor.eval.rubric import RubricEvaluator
from tutor.interfaces import LLMClient, Notifier, Synthesizer, Transcriber
from tutor.practice.engine import PracticeEngine
from tutor.practice.planner import DailyPlanner
from tutor.progress.tracker import ProgressTracker


def build_llm(settings: Settings) -> LLMClient:
    match settings.llm_backend:
        case "ollama":
            from tutor.adapters.llm.ollama import OllamaLLMClient

            return OllamaLLMClient(
                settings.ollama_base_url, settings.ollama_api_key, settings.ollama_model
            )
        case "mimo":
            from tutor.adapters.llm.mimo import MiMoLLMClient

            return MiMoLLMClient(settings.mimo_base_url, settings.mimo_api_key, settings.mimo_model)
        case "ollama_mimo":
            from tutor.adapters.llm.fallback import FallbackLLMClient
            from tutor.adapters.llm.mimo import MiMoLLMClient
            from tutor.adapters.llm.ollama import OllamaLLMClient

            primary = OllamaLLMClient(
                settings.ollama_base_url, settings.ollama_api_key, settings.ollama_model
            )
            fallback = MiMoLLMClient(
                settings.mimo_base_url, settings.mimo_api_key, settings.mimo_model
            )
            return FallbackLLMClient(primary, fallback)
        case _:
            from tutor.adapters.llm.stub import StubLLMClient

            return StubLLMClient()


def build_notifier(settings: Settings) -> Notifier:
    # Polling owns the single aiogram Bot and replaces this adapter in bot.main.
    # Other entry points (exports, tests, migrations) must not create an unclosed HTTP session.
    from tutor.adapters.notify.stub import StubNotifier

    return StubNotifier()


def build_transcriber(settings: Settings) -> Transcriber:
    if settings.stt_backend == "cloud":
        from tutor.adapters.stt.cloud import build_cloud_transcriber

        return build_cloud_transcriber(settings)
    if settings.stt_backend == "whisper":
        raise RuntimeError(
            "STT_BACKEND=whisper (local faster-whisper) is not implemented; "
            "use 'cloud' (Groq/OpenAI) or 'stub'."
        )
    from tutor.adapters.stt.stub import StubTranscriber

    return StubTranscriber()


def build_synthesizer(settings: Settings) -> Synthesizer:
    if settings.tts_backend == "groq":
        from tutor.adapters.tts.groq import build_groq_synthesizer

        return build_groq_synthesizer(settings)
    if settings.tts_backend in ("edge", "openai", "cloud"):
        raise RuntimeError(
            f"TTS_BACKEND={settings.tts_backend} is not implemented; use 'groq' or 'stub'."
        )
    from tutor.adapters.tts.stub import StubSynthesizer

    return StubSynthesizer()


@dataclass
class Services:
    """Everything the pipeline needs, with concrete adapters resolved."""

    settings: Settings
    repo: Repository
    llm: LLMClient
    notifier: Notifier
    transcriber: Transcriber
    synthesizer: Synthesizer
    audio_cues: AudioCueComposer
    catalog: BundledCatalog
    planner: DailyPlanner
    tracker: ProgressTracker
    engine: PracticeEngine
    evaluator: RubricEvaluator
    email_checker: StandaloneEmailChecker
    replenisher: CatalogReplenisher


def build_services(settings: Settings, conn: sqlite3.Connection) -> Services:
    repo = Repository(conn)
    llm = build_llm(settings)
    synthesizer = build_synthesizer(settings)
    catalog = BundledCatalog.load()
    tracker = ProgressTracker(repo)
    planner = DailyPlanner(repo, catalog)
    tracker.migrate_legacy_errors()
    engine = PracticeEngine(repo, tracker)
    evaluator = RubricEvaluator(repo, llm, tracker)
    email_checker = StandaloneEmailChecker(repo, llm, tracker)
    replenisher = CatalogReplenisher(
        repo, llm, HttpSourceFetcher(), synthesizer, settings.data_path / "catalog_audio"
    )
    return Services(
        settings=settings,
        repo=repo,
        llm=llm,
        notifier=build_notifier(settings),
        transcriber=build_transcriber(settings),
        synthesizer=synthesizer,
        audio_cues=AudioCueComposer(),
        catalog=catalog,
        planner=planner,
        tracker=tracker,
        engine=engine,
        evaluator=evaluator,
        email_checker=email_checker,
        replenisher=replenisher,
    )
