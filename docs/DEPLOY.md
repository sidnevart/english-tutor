# Deploying english-tutor

CI runs lint, formatting, catalog validation, and tests. A push to `main` then triggers the SSH deployment workflow when the repository variable `DEPLOY_ENABLED=true`.

## One-time VPS setup

```bash
ssh root@80.74.25.43
curl -fsSL https://raw.githubusercontent.com/sidnevart/english-tutor/main/deploy/bootstrap.sh | bash
```

Create `/opt/english-tutor/.env` from `.env.example`. Set the Telegram token and user ID, real STT/TTS backends for Speaking, and an LLM backend for open-response grading and replenishment. Then install the systemd unit:

The bootstrap also installs `ffmpeg`, which the Groq TTS adapter uses to produce Telegram-compatible OGG/Opus audio.

```bash
cd /opt/english-tutor
cp deploy/english-tutor-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now english-tutor-bot
journalctl -u english-tutor-bot -f
```

The single `tutor bot` process runs polling and four embedded jobs in `TZ`:

- daily plan delivery (`PRACTICE_PUSH_CRON`, default 08:00);
- writing deadline closure (every minute);
- pending rubric retries (every 15 minutes);
- catalog replenishment (`CATALOG_REPLENISH_CRON`, Sunday 04:00).

SQLite data in `/opt/english-tutor/data` survives code deployments. Startup creates new tables and migrates legacy `session_error` rows without deleting the old database.

## GitHub settings

Set `DEPLOY_ENABLED=true` and these secrets:

- `VPS_HOST`
- `VPS_USER`
- `VPS_SSH_KEY`

Every successful push to `main` pulls the new commit, runs `uv sync`, and restarts `english-tutor-bot`.
