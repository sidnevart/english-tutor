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

Deployment is via GitHub Actions (CI + SSH deploy) — see [docs/DEPLOY.md](docs/DEPLOY.md).
The optional Hermes voice/chat plane is documented in [docs/HERMES.md](docs/HERMES.md).

## Quickstart (offline, no secrets)

```bash
uv sync                       # create venv + install deps (Python 3.12)
uv run pytest                 # full stub loop runs offline, no network
uv run tutor --help           # CLI: bot | scheduler | scrape | ingest | llm-smoke
```

## Running for real

```bash
uv sync --extra scrape        # adds Telethon for channel scraping
# fill .env: BOT_TOKEN, TG_API_ID, TG_API_HASH, LLM_BACKEND=ollama
uv run tutor scrape           # pull articles from your channels
uv run tutor ingest           # pull today's podcasts (RSS)
uv run tutor llm-smoke        # verify Ollama returns valid quiz JSON
uv run tutor bot              # run the bot + embedded scheduler
```

Bot commands: `/start` (deliver a reading + quiz), `/next` (next reading),
`/coach <text>` (free-form practice), or send a voice message.

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

Feature-complete (M0–M9), built bottom-up in tiny, individually tested
milestones:

- **M0–M2** secret hygiene, config + state-machine repo, offline loop on stubs
- **M3** live Telegram scrape (Telethon) + interactive quiz bot
- **M4** real `glm-5:cloud` TOEFL questions
- **M5** scheduler (morning push + evening eval)
- **M6** podcasts (RSS) with cadence + lazy transcription
- **M7** native `SOUL.md` persona + per-user recall memory
- **M8** optional, sealed Hermes voice/chat plane
- **M9** CI/CD (GitHub Actions) deploy to the VPS

51 tests, lint-clean. Channel scrape, podcast feeds, and the LLM are all
live-validated.
