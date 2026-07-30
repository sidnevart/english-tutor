# english-tutor project structure

The product is a single-user TOEFL iBT 2026 Telegram trainer.

- `catalog/`: deterministic 60-day base, validation, duplicate checks, and source-backed replenishment.
- `practice/`: task vocabulary, calendar planner, durable attempt engine, grading, timers, and resume.
- `progress/`: canonical issue lifecycle, Reading skill mastery, reports, and MD/CSV/JSON export.
- `bot/`: focused commands, callbacks, task delivery, voice transport, and plan rendering.
- `scheduler/`: idempotent 08:00 delivery, deadline closure, evaluation retry, and weekly replenishment.
- `db/`: additive SQLite schema and repository.
- `eval/`: structured 0–5 rubrics for Interview, Email, and Academic Discussion.
- `interfaces/` and `adapters/`: LLM, notifier, STT, and TTS ports.

SQLite is the source of truth. Telegram FSM state is not required for recovery. The approved requirements live in `docs/superpowers/specs/2026-07-30-toefl-daily-practice-design.md`.

Run the gates with:

```bash
uv run tutor catalog-validate
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```
