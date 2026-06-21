"""Command-line entrypoint: `tutor <command>`.

Subcommands are wired up milestone by milestone. Until a real implementation
lands, a command prints where in the roadmap it arrives so the CLI always runs.
"""

from __future__ import annotations

import argparse
import sys


def _todo(milestone: str) -> int:
    print(f"[tutor] not yet implemented — arrives in milestone {milestone}")
    return 0


def _run_bot() -> int:
    import asyncio

    from tutor.bot.main import run_bot

    try:
        asyncio.run(run_bot())
    except RuntimeError as exc:
        print(f"[tutor] bot failed: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n[tutor] bot stopped.")
    return 0


def _run_eval_cards() -> int:
    """Eval the flashcard prompt against the real LLM with quality metrics."""
    import asyncio

    from tutor.adapters.llm.ollama import OllamaLLMClient
    from tutor.config import get_settings
    from tutor.eval.flashcards import _present, make_flashcards

    samples = [
        (
            "science",
            "The mitochondrion is often called the powerhouse of the cell because it "
            "generates most of the cell's supply of ATP. Researchers recently stumbled "
            "upon a serendipitous finding that could shed light on ageing.",
        ),
        (
            "idioms",
            "When the startup hit rock bottom, the founders had to think outside the box. "
            "They bit the bullet, cut their losses, and pivoted. In hindsight it was a "
            "blessing in disguise that paid off down the road.",
        ),
    ]
    s = get_settings()

    async def go() -> None:
        llm = OllamaLLMClient(s.ollama_base_url, s.ollama_api_key, s.ollama_model)
        for name, text in samples:
            cards = await make_flashcards(llm, text, limit=6)
            in_text = sum(1 for c in cards if _present(c.front, text))
            idioms = sum(1 for c in cards if "idiom" in c.tags)
            print(
                f"\n[{name}] {len(cards)} cards | in-text {in_text}/{len(cards)} | idioms {idioms}"
            )
            for c in cards:
                tag = "idiom" if "idiom" in c.tags else "word "
                print(f"  ({tag}) {c.front} -> {c.back[:100].replace(chr(10), ' / ')}")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] eval-cards failed: {exc}")
        return 1
    return 0


def _run_eval_speak() -> int:
    """Show a generated speaking task + a discussion opener from the real LLM."""
    import asyncio

    from tutor.adapters.llm.ollama import OllamaLLMClient
    from tutor.config import get_settings

    s = get_settings()
    passage = (
        "The mitochondrion is the powerhouse of the cell, generating most of its ATP. "
        "Researchers recently found it also helps regulate ageing."
    )

    async def go() -> None:
        llm = OllamaLLMClient(s.ollama_base_url, s.ollama_api_key, s.ollama_model)
        task = await llm.complete(
            "You are a TOEFL speaking coach. Give ONE short TOEFL-style speaking task "
            "(1-2 sentences).",
            "Begin.",
        )
        print("SPEAKING TASK:\n  " + task.strip())
        opener = await llm.complete(
            "You are a TOEFL coach. Open a discussion with ONE engaging question about "
            f"this passage.\n\nPASSAGE:\n{passage}",
            "Begin.",
        )
        print("\nDISCUSS OPENER:\n  " + opener.strip())

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] eval-speak failed: {exc}")
        return 1
    return 0


def _run_tts_smoke() -> int:
    """Synthesize one short clip with the configured TTS backend."""
    import asyncio
    from pathlib import Path

    from tutor.config import get_settings
    from tutor.factory import build_synthesizer

    s = get_settings()

    async def go() -> None:
        synth = build_synthesizer(s)
        out = Path(s.data_dir) / "tts_smoke.ogg"
        path = await synth.synthesize(
            "Hello! This is your TOEFL speaking coach. Let's practice.", out
        )
        size = path.stat().st_size
        print(f"[tutor] TTS ok: {path} ({size} bytes) backend={s.tts_backend} voice={s.tts_voice}")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] tts-smoke failed: {exc}")
        return 1
    return 0


def _run_llm_smoke() -> int:
    import asyncio

    from tutor.adapters.llm.ollama import OllamaLLMClient
    from tutor.config import get_settings
    from tutor.eval.schemas import ReadingQuizPayload

    s = get_settings()
    passage = (
        "The mitochondrion is often called the powerhouse of the cell because it "
        "generates most of the cell's supply of ATP, used as chemical energy. "
        "Mitochondria also play roles in signaling, differentiation, and cell death."
    )

    async def go() -> None:
        llm = OllamaLLMClient(s.ollama_base_url, s.ollama_api_key, s.ollama_model)
        print(f"[tutor] querying {s.ollama_model} at {s.ollama_base_url} ...")
        payload = await llm.complete_json(
            "You are a TOEFL reading-comprehension coach.",
            f"Write 2 multiple-choice questions (4 options each) about: {passage}",
            ReadingQuizPayload,
        )
        print(f"[tutor] OK — {len(payload.questions)} valid question(s):")
        for i, q in enumerate(payload.questions, 1):
            print(f"  Q{i}: {q.prompt}")
            for j, opt in enumerate(q.options):
                print(f"     {'*' if j == q.correct_index else ' '} {opt}")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] llm-smoke failed: {exc}")
        return 1
    return 0


def _run_scheduler() -> int:
    import asyncio

    from tutor.scheduler.runner import run_scheduler

    try:
        asyncio.run(run_scheduler())
    except RuntimeError as exc:
        print(f"[tutor] scheduler failed: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n[tutor] scheduler stopped.")
    return 0


def _run_ingest() -> int:
    import asyncio

    from tutor.app import open_services
    from tutor.ingest.rss import run_ingest

    async def go() -> None:
        with open_services() as svc:
            counts = await run_ingest(svc.settings, svc.repo)
            for name, n in counts.items():
                print(f"  {name}: +{n}")
            print(f"[tutor] ingested {sum(counts.values())} new episode(s)")

    try:
        asyncio.run(go())
    except RuntimeError as exc:
        print(f"[tutor] ingest failed: {exc}")
        return 1
    return 0


def _run_scrape() -> int:
    import asyncio

    from tutor.app import open_services
    from tutor.ingest.telegram_scraper import run_scrape

    async def go() -> None:
        with open_services() as svc:
            counts = await run_scrape(svc.settings, svc.repo)
            total = sum(counts.values())
            for channel, n in counts.items():
                print(f"  channel {channel}: +{n} new")
            print(f"[tutor] scraped {total} new item(s)")

    try:
        asyncio.run(go())
    except RuntimeError as exc:
        print(f"[tutor] scrape failed: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bot", help="run the Telegram bot (+ embedded scheduler)")
    sub.add_parser("scheduler", help="run the scheduler standalone")
    sub.add_parser("scrape", help="scrape the configured Telegram channels once")
    sub.add_parser("ingest", help="fetch RSS podcast feeds once")
    sub.add_parser("llm-smoke", help="check the configured LLM backend returns valid quiz JSON")
    sub.add_parser("eval-cards", help="eval the flashcard prompt against the real LLM")
    sub.add_parser("eval-speak", help="show a generated speaking task + discussion opener")
    sub.add_parser("tts-smoke", help="synthesize one clip with the configured TTS backend")

    args = parser.parse_args(argv)

    match args.command:
        case "bot":
            return _run_bot()
        case "scheduler":
            return _run_scheduler()
        case "scrape":
            return _run_scrape()
        case "ingest":
            return _run_ingest()
        case "llm-smoke":
            return _run_llm_smoke()
        case "eval-cards":
            return _run_eval_cards()
        case "eval-speak":
            return _run_eval_speak()
        case "tts-smoke":
            return _run_tts_smoke()
        case _:  # pragma: no cover
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
