# english-tutor

Autonomous, self-hosted **TOEFL preparation assistant** for Telegram. It turns
daily content consumption into an active learning loop:

- **Morning** — delivers articles scraped from your Telegram channels and
  podcasts pulled from RSS.
- **Evening** — runs interactive TOEFL-style evaluation: reading-comprehension
  quizzes + vocabulary checks on the exact words from the day's text.
- **Always** — auto-generates Anki cards from what you got wrong.

## Architecture (two planes)

A **deterministic core** (SQLite state machine → APScheduler → aiogram
inline-keyboard UX → evaluation) talks to **Ollama directly** behind an
`LLMClient` port. A **sealed, optional Hermes Agent plane** can be switched on
later purely for free-form voice/chat practice — it is never on the critical
path. Every external dependency (LLM, STT, TTS, Anki, Telegram) is a Protocol
with a stub + real implementation, swapped via a one-line `.env` change, so the
**entire loop runs offline on stubs**.

See [`docs`/the plan] for the full design and milestone roadmap.

## Quickstart (offline, no secrets)

```bash
uv sync                       # create venv + install deps (Python 3.12)
uv run pytest                 # full stub loop runs offline, no network
uv run tutor --help           # CLI: bot | scheduler | scrape | ingest | llm-smoke
```

## Configuration

All config is read strictly from `.env` (see `.env.example`). Everything
defaults to safe **stubs**, so the app runs with an empty `.env`. Fill in real
keys only as you enable each real backend:

| Backend | env switch | stub → real |
|---|---|---|
| LLM | `LLM_BACKEND` | `stub` → `ollama` (→ `hermes`) |
| STT | `STT_BACKEND` | `stub` → `whisper` / `cloud` |
| TTS | `TTS_BACKEND` | `stub` → `edge` / `cloud` |
| Anki | `ANKI_BACKEND` | `genanki` (.apkg) / `ankiconnect` / `null` |
| Notifier | `NOTIFIER_BACKEND` | `stub` → `telegram` |

> **Secrets:** `.env`, `bot_data/` (Telegram sessions) and `data/` are
> git-ignored. Never commit them.

## Status

Built bottom-up in tiny, individually testable milestones (M0 hygiene → M9
hardening). The offline foundation (M0–M2) lands first; the live Telegram +
Ollama slice (M3+) follows once credentials are provided.
