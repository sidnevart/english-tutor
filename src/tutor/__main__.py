"""Command-line entrypoint: `tutor <command>`.

bot        — run the Telegram bot (+ embedded scheduler)
scheduler  — run the scheduler standalone (no polling)
llm-smoke  — check the configured LLM (complete + complete_json)
tts-smoke  — synthesize one clip with the configured TTS backend
diary      — export the error diary to disk (no Telegram needed)
"""

from __future__ import annotations

import argparse
import sys


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


def _run_llm_smoke() -> int:
    """Check the configured LLM returns text and valid feedback JSON."""
    import asyncio

    from tutor.adapters.llm.ollama import OllamaLLMClient
    from tutor.config import get_settings
    from tutor.eval.schemas import SessionFeedbackPayload

    s = get_settings()

    async def go() -> None:
        llm = OllamaLLMClient(s.ollama_base_url, s.ollama_api_key, s.ollama_model)
        print(f"[tutor] querying {s.ollama_model} at {s.ollama_base_url} ...")
        txt = await llm.complete("You are an English practice coach.", "Say hello in one sentence.")
        print(f"[tutor] complete() OK: {txt.strip()[:120]}")
        payload = await llm.complete_json(
            "You are an English coach analyzing a learner's sentence for errors.",
            'Learner said: "I goes to school yesterday." Return the feedback JSON.',
            SessionFeedbackPayload,
        )
        print(
            f"[tutor] complete_json() OK: {len(payload.errors)} error(s); "
            f"assessment='{(payload.assessment or '')[:80]}'"
        )

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] llm-smoke failed: {exc}")
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
        path = await synth.synthesize("Hello! Let's practise some English today.", out)
        size = path.stat().st_size
        print(f"[tutor] TTS ok: {path} ({size} bytes) backend={s.tts_backend} voice={s.tts_voice}")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] tts-smoke failed: {exc}")
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


def _run_diary() -> int:
    """Export the error diary to disk (Markdown + CSV + Anki), no Telegram."""
    import asyncio
    from pathlib import Path

    from tutor.app import open_services
    from tutor.export.diary import error_card, markdown_diary, write_csv_diary

    async def go() -> None:
        with open_services() as svc:
            uid = svc.settings.admin_user_id
            rows = svc.repo.error_diary(uid)
            if not rows:
                print("[tutor] the error diary is empty.")
                return
            out = Path("diary_export")
            out.mkdir(exist_ok=True)
            md = out / "diary.md"
            md.write_text(markdown_diary(rows), encoding="utf-8")
            csv_path = out / "diary.csv"
            write_csv_diary(rows, csv_path)
            res = await svc.anki.add_cards(
                svc.settings.anki_deck, [error_card(r) for r in rows[:40]]
            )
            total = sum(int(r["count"]) for r in rows)
            print(f"[tutor] diary: {len(rows)} distinct errors, {total} occurrences")
            print(f"  {md}")
            print(f"  {csv_path}")
            if res.apkg_path:
                print(f"  {res.apkg_path}")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] diary failed: {exc}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bot", help="run the Telegram bot (+ embedded scheduler)")
    sub.add_parser("scheduler", help="run the scheduler standalone")
    sub.add_parser("llm-smoke", help="check the configured LLM (complete + JSON)")
    sub.add_parser("tts-smoke", help="synthesize one clip with the configured TTS backend")
    sub.add_parser("diary", help="export the error diary to disk")

    args = parser.parse_args(argv)

    match args.command:
        case "bot":
            return _run_bot()
        case "scheduler":
            return _run_scheduler()
        case "llm-smoke":
            return _run_llm_smoke()
        case "tts-smoke":
            return _run_tts_smoke()
        case "diary":
            return _run_diary()
        case _:  # pragma: no cover
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
