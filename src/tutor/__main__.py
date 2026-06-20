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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tutor", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("bot", help="run the Telegram bot (+ embedded scheduler)")
    sub.add_parser("scheduler", help="run the scheduler standalone")
    sub.add_parser("scrape", help="scrape the configured Telegram channels once")
    sub.add_parser("ingest", help="fetch RSS podcast feeds once")
    sub.add_parser("llm-smoke", help="check the configured LLM backend returns valid quiz JSON")

    args = parser.parse_args(argv)

    match args.command:
        case "bot":
            return _todo("M3")
        case "scheduler":
            return _todo("M5")
        case "scrape":
            return _todo("M3")
        case "ingest":
            return _todo("M6")
        case "llm-smoke":
            return _todo("M4")
        case _:  # pragma: no cover
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
