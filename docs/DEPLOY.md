# Deploying english-tutor to the VPS (CI/CD)

Two GitHub Actions workflows:

- **CI** (`.github/workflows/ci.yml`) — runs `ruff` + `pytest` on every push/PR.
- **Deploy** (`.github/workflows/deploy.yml`) — on push to `main`, SSHes into the
  VPS, pulls, `uv sync`, and restarts the systemd service. It is **gated** by the
  `DEPLOY_ENABLED` repo variable, so it stays dormant until you opt in.

## 1. One-time server bootstrap

SSH into the VPS and run the bootstrap (clones to `/opt/english-tutor`, installs
uv + deps):

```bash
ssh root@80.74.25.43
curl -fsSL https://raw.githubusercontent.com/sidnevart/english-tutor/main/deploy/bootstrap.sh | bash
```

Then complete the manual, secret steps it prints:

1. Create `/opt/english-tutor/.env` from `.env.example` (BOT_TOKEN, TG_API_ID,
   TG_API_HASH, ADMIN_USER_ID, `LLM_BACKEND=ollama`, …).
2. Copy your Telegram session to `/opt/english-tutor/bot_data/`.
3. Install Ollama and `ollama signin` (needed for the cloud-routed `glm-5:cloud`).
4. Install + start the service:
   ```bash
   cd /opt/english-tutor
   cp deploy/english-tutor-bot.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now english-tutor-bot
   ```

`tutor bot` runs the bot **and** the embedded scheduler (morning push + evening
eval). Logs: `journalctl -u english-tutor-bot -f`.

## 2. Enable CI/CD auto-deploy

In the GitHub repo settings:

- **Variables** → add `DEPLOY_ENABLED = true`.
- **Secrets** → add:
  - `VPS_HOST` = `80.74.25.43`
  - `VPS_USER` = `root`
  - `VPS_SSH_KEY` = a private key whose public half is in the VPS
    `~/.ssh/authorized_keys` (recommended), **or** switch the workflow to
    `password: ${{ secrets.VPS_PASSWORD }}` and add `VPS_PASSWORD`.

Now every push to `main` deploys automatically. Trigger manually any time via
the **Deploy** workflow's "Run workflow" button.

## 3. Scheduled content (optional)

The embedded scheduler handles morning/evening jobs. To also refresh content on a
cadence, add cron entries on the VPS:

```cron
0 7 * * *  cd /opt/english-tutor && /root/.local/bin/uv run tutor scrape
5 7 * * *  cd /opt/english-tutor && /root/.local/bin/uv run tutor ingest
```

## Notes

- Secrets (`.env`, `bot_data/`) are never in git; they live only on the server.
- The deploy step is idempotent: pull → sync → restart.
- Roll back by checking out a previous commit on the server and restarting.
