"""Command-line entrypoint for the focused TOEFL practice bot."""

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
    import asyncio

    from tutor.config import get_settings
    from tutor.eval.rubric import RubricEvaluation
    from tutor.factory import build_llm

    settings = get_settings()

    async def go() -> None:
        llm = build_llm(settings)
        payload = await llm.complete_json(
            "Evaluate a TOEFL practice email on a 0-5 scale.",
            "Dear Coordinator, I am writing to request a schedule change.",
            RubricEvaluation,
        )
        print(f"[tutor] structured LLM OK: score={payload.score}, confidence={payload.confidence}")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] llm-smoke failed: {exc}")
        return 1
    return 0


def _run_tts_smoke() -> int:
    import asyncio

    from tutor.config import get_settings
    from tutor.factory import build_synthesizer

    settings = get_settings()

    async def go() -> None:
        synth = build_synthesizer(settings)
        path = await synth.synthesize(
            "The campus library opens at eight tomorrow.",
            settings.data_path / "tts_smoke.wav",
        )
        print(f"[tutor] TTS OK: {path} ({path.stat().st_size} bytes)")

    try:
        asyncio.run(go())
    except Exception as exc:  # noqa: BLE001
        print(f"[tutor] tts-smoke failed: {exc}")
        return 1
    return 0


def _run_export(fmt: str) -> int:
    from tutor.app import open_services
    from tutor.progress.exporter import export_progress

    with open_services() as svc:
        path = export_progress(
            svc.repo, svc.settings.admin_user_id, fmt, svc.settings.data_path / "exports"
        )
        print(path)
    return 0


def _validate_catalog() -> int:
    from tutor.catalog import BundledCatalog

    catalog = BundledCatalog.load()
    errors = catalog.validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"[tutor] catalog OK: {len(catalog.tasks)} validated blocks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bot", help="run Telegram polling and the embedded scheduler")
    sub.add_parser("llm-smoke", help="check structured LLM evaluation")
    sub.add_parser("tts-smoke", help="synthesize one Speaking prompt")
    export_parser = sub.add_parser("export", help="export the learning profile")
    export_parser.add_argument("--format", choices=("md", "csv", "json"), default="md")
    sub.add_parser("catalog-validate", help="validate all bundled TOEFL tasks")
    args = parser.parse_args(argv)
    match args.command:
        case "bot":
            return _run_bot()
        case "llm-smoke":
            return _run_llm_smoke()
        case "tts-smoke":
            return _run_tts_smoke()
        case "export":
            return _run_export(args.format)
        case "catalog-validate":
            return _validate_catalog()
        case _:
            return 1


if __name__ == "__main__":
    sys.exit(main())
