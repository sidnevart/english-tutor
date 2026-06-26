# english-tutor

Autonomous, self-hosted **TOEFL preparation assistant** for Telegram. It turns
daily content consumption into an active learning loop:

- **Morning** — delivers articles and podcasts, each with a words+idioms Anki
  deck. A single **daily TOEFL file** is sent alongside: one self-contained
  Markdown file with a Reading passage, Listening questions (audio attached),
  and Vocabulary exercises. Fill in your answers and send the file back.
- **Evening** — the bot nudges you to complete the daily file and practice
  Speaking (`/speaking`, 4 official task types, scored 0-4) and Writing (`/write`,
  essay task file, scored 0-5 with rubric feedback).
- **Always** — Anki cards auto-generated from missed words; `/progress` shows
  streak, accuracy trends, weak topics, and recurring errors.

## Architecture (two planes)

A **deterministic core** (SQLite state machine → APScheduler → aiogram
inline-keyboard UX → evaluation) talks to **Ollama directly** behind an
`LLMClient` port. A **sealed, optional Hermes Agent plane** can be switched on
later purely for free-form voice/chat practice — it is never on the critical
path. Every external dependency (LLM, STT, TTS, Anki, Telegram) is a Protocol
with a stub + real implementation, swapped via a one-line `.env` change, so the
**entire loop runs offline on stubs**.

Deployment is via GitHub Actions (CI + SSH deploy) — see [docs/DEPLOY.md](docs/DEPLOY.md).

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
uv run tutor scrape           # pull text articles from your Telegram channels
uv run tutor ingest           # pull today's podcasts (RSS)
uv run tutor llm-smoke        # verify Ollama returns valid quiz JSON
uv run tutor bot              # run the bot + embedded scheduler
```

## Bot commands

| Command | What it does |
|---------|--------------|
| `/start` | Register and deliver today's first reading/episode |
| `/next` | Deliver the next reading or episode |
| `/daily` | Get today's TOEFL file (Reading + Listening + Vocab) |
| `/speaking` | Strict TOEFL Speaking: 4 task types, timed, scored 0-4 |
| `/write` | TOEFL writing task file (essay, graded 0-5) |
| `/speak` | Free-form spoken practice (voice or text) |
| `/coach` | Adaptive coaching session |
| `/review` | Evening grammar/vocabulary/comprehension review |
| `/cards` | Today's Anki cards (`more` for extra, `all` for full deck) |
| `/progress` | Stats: streak, accuracy trends, weak topics, vocab |
| `/reset` | Wipe all progress and start fresh |
| `/help` | Show all commands and the daily-loop guide |

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

## Content sources

Articles are fetched from **The Guardian Open Platform** (curated, TOEFL-scale
length) and **Telegram channels** (text posts only — PDF/EPUB/FB2 magazines are
no longer parsed to avoid oversized content). Podcasts come from a hand-picked
RSS catalog: NPR Short Wave, The Indicator, TED Tech, Planet Money, BBC 6 Minute
English, and more.

## Status

Feature-complete (M0–M9), with a consolidated daily-file loop, file-based
Speaking and Writing flows, and a dynamic progress dashboard with weekly trends.

51+ tests, lint-clean. All loops run offline on stubs; live-validated with real
LLM, TTS, and Telegram integrations.