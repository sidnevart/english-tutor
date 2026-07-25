# english-tutor — Project Structure

> Living reference. Read this before changing the bot. Last updated after the
> **error-diary repivot** (TOEFL/content machinery removed; the bot's job is now
> *speaking/writing practice that captures your errors into an exportable diary*).

## 1. What this bot is

A single-user Telegram bot for **English speaking & writing practice that tracks
your mistakes**. You practise (the bot gives you a topic, you answer by voice or
text), and on `/stop` it extracts every error into a **diary** you can export
(`/diary` → Markdown + CSV + Anki). A scheduler starts a practice for you a few
times a week.

**Stack:** Python 3.12 · aiogram 3.x (Telegram) · APScheduler · SQLite (raw
`sqlite3`, no ORM) · LLM/STT/TTS via OpenAI-compatible adapters · genanki (`.apkg`).

## 2. Directory tree

```
english-tutor/
├─ src/tutor/
│  ├─ __main__.py          # CLI entrypoint: `tutor bot|scheduler|llm-smoke|tts-smoke|diary`
│  ├─ app.py               # Composition root: open_services() — DB + wired Services
│  ├─ config.py            # Settings(BaseSettings) — the ONLY env reader
│  ├─ factory.py           # Adapter selection: config → concrete impls + Services dataclass
│  ├─ topics.py            # Static SPEAKING_TOPICS / WRITING_TOPICS + pick_topic(kind, idx)
│  │
│  ├─ bot/                 # Telegram layer
│  │  ├─ main.py           # run_bot(): Bot+Dispatcher, router, set_my_commands, scheduler
│  │  ├─ handlers.py       # build_router(): all commands + /diary + FSM message handlers
│  │  ├─ conversation.py   # The practice engine: start_practice / handle_turn / end_session
│  │  └─ keyboards.py      # reset_confirm(), parse_callback()
│  │
│  ├─ scheduler/
│  │  ├─ jobs.py           # push_practice (Mon/Wed/Fri) + weekly_summary (Sun)
│  │  └─ runner.py         # build_scheduler(): registers cron jobs; run_scheduler() standalone
│  │
│  ├─ export/
│  │  └─ diary.py          # export_diary() → Markdown + CSV + Anki; markdown/csv/card helpers
│  │
│  ├─ eval/
│  │  └─ schemas.py        # SessionError, SessionFeedbackPayload (the error-capture contract)
│  │
│  ├─ memory/
│  │  ├─ recall.py         # Memory: SOUL persona + per-user weak_words.md recall
│  │  ├─ context.py        # build_learner_context(): streak+errors+weak vocab → prompt context
│  │  └─ soul.py           # load_soul() (soul/SOUL.md persona)
│  │
│  ├─ domain/
│  │  └─ models.py         # Card, AnkiResult (Anki note types)
│  │
│  ├─ db/
│  │  ├─ connection.py     # connect(), init_db() (applies schema.sql + _migrate)
│  │  ├─ repository.py     # Repository: SOLE DB writer (intent verbs, no raw SQL elsewhere)
│  │  └─ schema.sql        # DDL: subscriber, session_error, schedule_log (+ index)
│  │
│  ├─ interfaces/          # Ports (Protocols): anki, llm, notifier, synthesizer, transcriber
│  └─ adapters/            # Concrete impls: llm/, stt/, tts/, anki/, notify/
│
├─ tests/                  # pytest (asyncio_mode=auto). Fixtures in conftest.py
├─ soul/                   # SOUL.md coach persona (+ memory/<uid>/ weak_words.md, USER.md)
├─ data/                   # SQLite db + generated files (diary_*.md/csv, *.apkg). git-ignored.
├─ deploy/                 # systemd unit (english-tutor-bot.service)
├─ .github/workflows/      # ci.yml (lint+format+test), deploy.yml (SSH to VPS)
└─ pyproject.toml          # deps, ruff, pytest config; `tutor` script entrypoint
```

## 3. The error-diary loop (data flow)

```
  push_practice (cron Mon/Wed/Fri)  ──or──  /speak · /write (manual)
                │
                ▼
   start_practice(kind)  [conversation.py]
     · pick_topic(kind, idx) from topics.py   (static pool — no LLM call)
     · bump topic_idx in subscriber.prefs_json
     · enter ConversationState.active (FSM), seed history=[{coach: topic}]
                │
                ▼
   learner replies (voice → download_voice→STT, or text)
                │
                ▼
   handle_turn()  · appends to history · LLM reply (inline corrections) · _say()
                │  (repeatable — multi-turn)
                ▼
   /stop → end_session()
     · LLM complete_json → SessionFeedbackPayload{ strengths, errors[], … }
     · repo.save_session_errors(user_id, mode, errors)   ◀── THE CAPTURE
                │
                ▼
   session_error table  (source of truth for the diary)
                │
        ┌───────┴────────┐
        ▼                ▼
   /progress (stats)   /diary → export_diary()
                          · error_diary() repo query (count, first/last seen, last ctx)
                          · markdown_diary / write_csv_diary / error_card → .apkg
                          · Notifier.send_file ×3
```

**Two capture paths, one table:** speaking (`mode="speak"`) and writing
(`mode="write"`) both flow through `end_session` → `save_session_errors`.
`/coach` sessions also capture (`mode="coach"`). There is no separate essay table.

## 4. Key concepts

- **FSM (`ConversationState.active`)** — aiogram in-memory state, keyed by
  (bot_id, chat_id, user_id). Holds `mode` + `history`. `push_practice` enters it
  via the shared `dp.storage` so the learner's reply hits the normal handlers.
  State is lost on restart (acceptable for single-user); an open session just
  expires.
- **`session_error`** — one row per *occurrence* of an error: `(user_id,
  session_type, error_type[grammar|vocab|phrasing], error_text, correction,
  context, created_at)`. Dedup/aggregation happens at read time
  (`top_session_errors`, `error_diary`) by exact `(error_type, error_text)`.
- **`prefs_json`** — JSON blob on `subscriber`; holds `next_practice` (speak↔write
  alternation) and `topic_idx` (round-robin through the topic pool). Cleared by
  `/reset`.
- **Topics are static** (`topics.py`) so a push always starts even if the LLM is
  down. The LLM is used only for turns + end-of-session error extraction.
- **Services (factory.py)** — the wired dependency bundle passed everywhere:
  `settings, repo, llm, notifier, anki, transcriber, synthesizer`.

## 5. Schema (`db/schema.sql`) — 3 tables

| table          | purpose                                              |
|----------------|------------------------------------------------------|
| `subscriber`   | `user_id` PK, `joined_at`, `prefs_json`              |
| `session_error`| the diary (see above); index on `(user_id, created_at)` |
| `schedule_log` | job run diagnostics (`job, run_at, status, detail`)  |

No migrations tool. `init_db()` runs `schema.sql` (idempotent `CREATE … IF NOT
EXISTS`) + `_migrate()` (additive `ALTER TABLE` list, currently empty). Old tables
from the TOEFL era are **not** auto-dropped — delete `data/tutor.db` for a clean
slate (single-user bot).

## 6. Commands (`bot/handlers.py` COMMANDS)

`/start /speak /write /coach /stop /diary /progress /reset /help`
(`/diary [md|csv|apkg]` — no arg = all three). `HELP_TEXT` must stay in sync with
`COMMANDS` — `tests/test_help.py` enforces it (and HTML escaping).

## 7. Config (`config.py` → `.env`)

All defaults are offline stubs, so an empty `.env` runs. Key vars:
- `BOT_TOKEN`, `ADMIN_USER_ID` (the single learner; default 764315256)
- Backends: `LLM_BACKEND` (stub|ollama|hermes|mimo|ollama_mimo), `STT_BACKEND`
  (stub|cloud), `TTS_BACKEND` (stub|groq), `ANKI_BACKEND` (genanki|ankiconnect|null),
  `NOTIFIER_BACKEND` (stub|telegram)
- LLM: `OLLAMA_BASE_URL`/`OLLAMA_MODEL`/`OLLAMA_API_KEY` (default glm-5:cloud);
  `MIMO_*`, `HERMES_*` fallbacks
- STT/TTS cloud: `GROQ_API_KEY`, `OPENAI_API_KEY`, `STT_MAX_SECONDS`, `TTS_VOICE`
- Schedule: `PRACTICE_PUSH_CRON` (default `23 19 * * 1,3,5`),
  `WEEKLY_SUMMARY_CRON` (default `47 10 * * 0`), `TZ` (Europe/Moscow)
- `ANKI_DECK` (default `English::Errors`), `DB_PATH`, `DATA_DIR`, `SOUL_DIR`

## 8. Adapters (`interfaces/` ports → `adapters/` impls)

`factory.py` is the ONLY place mapping config→impl. Reals import lazily so the
stub path never touches network clients. Notable: graded/JSON output
(`complete_json`) is the LLM's structured path used by `end_session`.

## 9. Run / test / lint / deploy

```bash
uv sync                          # install deps
uv run pytest                    # tests (asyncio_mode=auto)
uv run ruff check src tests      # lint
uv run ruff format --check src tests
uv run tutor bot                 # run bot (+ embedded scheduler); needs BOT_TOKEN
uv run tutor diary               # export diary to ./diary_export (no Telegram)
# Offline smoke (no secrets): LLM/STT/TTS/NOTIFIER_BACKEND=stub
```

**Deploy:** `deploy/english-tutor-bot.service` (systemd, `uv run tutor bot`).
GitHub Actions `deploy.yml` SSHes to the VPS, `git pull` + `uv sync` +
`systemctl restart english-tutor-bot` — gated by repo variable
`DEPLOY_ENABLED=true` + secrets (`VPS_HOST/USER/SSH_KEY`); `continue-on-error`.

## 10. Common change recipes

- **Add a practice topic** → append to `SPEAKING_TOPICS`/`WRITING_TOPICS` in
  `topics.py`. Round-robin picks it up automatically.
- **Change push cadence** → `PRACTICE_PUSH_CRON` in `config.py` / `.env`; job
  wired in `scheduler/runner.py`.
- **Add a command** → handler in `handlers.py` `build_router()` + entry in
  `COMMANDS` + line in `HELP_TEXT` (test_help enforces sync).
- **Switch LLM** → `LLM_BACKEND` + creds in `.env` (no code change).
- **Change the diary output** → `export/diary.py` (`markdown_diary`,
  `write_csv_diary`, `error_card`); columns controlled by `_CSV_COLUMNS`.
- **Add a DB column** → add to `schema.sql` AND to `_migrate()` in
  `connection.py` (for pre-existing DBs); touch `reset_progress` if user-scoped.
- **Tune error extraction** → the prompt is inline in `conversation.py:end_session`
  + the `SessionFeedbackPayload` schema in `eval/schemas.py`.

## 11. Gotchas

- **Writing is inline in chat**, not file-based — both speak/write share
  `end_session`. In write mode coach replies are text-only (no TTS).
- **`push_practice` from the scheduler** enters FSM via `dp.storage` (embedded
  scheduler only). Standalone `tutor scheduler` uses a fresh MemoryStorage — the
  push message still sends, but FSM state is process-local.
- **Error dedup is exact-text** (`error_type`+`error_text`). Near-duplicate
  phrasings fragment. If the diary gets noisy, add a normalized `error_key`
  column (schema.sql + `_migrate`) and group on it in `error_diary`.
