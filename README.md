# english-tutor

Single-user Telegram trainer for the TOEFL iBT format introduced on January 21, 2026.

Every day at 08:00 Europe/Moscow the bot sends one durable plan:

- Reading every day: Complete the Words, Read in Daily Life, or Academic Passage;
- Speaking every day: Listen and Repeat or Take an Interview;
- Writing every second calendar day: Build a Sentence, Email, or Academic Discussion.

The repository includes a validated 60-day catalog, so scheduled practice does not wait for an LLM or a website. A weekly background job can add original tasks from bounded factual briefs taken from an allowlist of NASA, NOAA, USGS, Smithsonian, university, and official-public-notice sites. Source text is never republished.

## Practice mechanics

- SQLite owns plans, answers, deadlines, scores, and the active item. A restart resumes the exact step.
- Reading and Build a Sentence are graded deterministically.
- Listen and Repeat compares the hidden source sentence with the transcript and reports a 0–5 estimate per item.
- Interview, Email, and Academic Discussion use separate schema-validated 0–5 rubrics. A failed evaluation stays pending and retries automatically.
- The learning profile groups equivalent issues by canonical skill, records improvement and relapse, and covers Reading as well as Speaking and Writing.
- `/export`, `/export csv`, and `/export json` produce a current portable profile. There is no Anki integration.

Training scores are practice estimates, not official TOEFL section scores.

## Commands

| Command | Action |
| --- | --- |
| `/start` | Register and show today's plan |
| `/today` | Show the same durable daily plan |
| `/reading` | Open today's Reading block |
| `/speaking` | Open today's Speaking block |
| `/writing` | Open Writing when it is due |
| `/progress` | Show completion, task results, skills, and issue states |
| `/export [md\|csv\|json]` | Export the latest learning profile |
| `/cancel` | Pause the active block without deleting answers |
| `/reset` | Erase learner progress after confirmation |
| `/help` | Explain the loop |

## Setup

Requires Python 3.12 and `uv`.

```bash
cp .env.example .env
uv sync
uv run tutor catalog-validate
uv run pytest
uv run ruff check src tests
uv run ruff format --check src tests
uv run tutor bot
```

For the live bot set `BOT_TOKEN`, `ADMIN_USER_ID`, `NOTIFIER_BACKEND=telegram`, `STT_BACKEND=cloud`, and `TTS_BACKEND=groq`. Configure `LLM_BACKEND=ollama`, `mimo`, or `ollama_mimo` for open-response evaluation and catalog generation. Offline stubs remain useful for tests, but stub STT/TTS do not produce usable Speaking audio.

Useful diagnostics:

```bash
uv run tutor llm-smoke
uv run tutor tts-smoke
uv run tutor export --format md
```

## Persistence and content policy

`data/tutor.db` is the source of truth. Startup migrations are additive: existing `session_error` rows are converted idempotently into canonical learning issues, and no old database is deleted automatically.

Bundled tasks are original editorial material with stable IDs. Generated tasks pass deterministic count, length, answer, evidence, duplicate, and audio checks plus an independent LLM critic before becoming eligible. Britannica is excluded from the default allowlist.

See [the approved design](docs/superpowers/specs/2026-07-30-toefl-daily-practice-design.md) and [deployment guide](docs/DEPLOY.md).
