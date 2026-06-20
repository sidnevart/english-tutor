#!/usr/bin/env bash
# One-time VPS setup for english-tutor. Run as the deploy user (e.g. root).
#   curl -fsSL .../bootstrap.sh | bash   — or copy and run it on the server.
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/english-tutor}"
REPO="${REPO:-https://github.com/sidnevart/english-tutor.git}"

# 1. Install uv if missing.
if [ ! -x "$HOME/.local/bin/uv" ] && ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$HOME/.local/bin/uv"

# 2. Clone or update the code.
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

# 3. Install dependencies (incl. the Telegram scraper extra).
"$UV" sync --extra scrape

cat <<'NOTE'

✅ Code + deps installed.

One-time manual steps (secrets are intentionally NOT in git):

  1. Create /opt/english-tutor/.env from .env.example and fill at least:
       BOT_TOKEN, TG_API_ID, TG_API_HASH, ADMIN_USER_ID, LLM_BACKEND=ollama
  2. Copy your Telegram session to /opt/english-tutor/bot_data/
       (telegram_e2e_session.session)
  3. Install Ollama and sign in (glm-5:cloud is cloud-routed):
       curl -fsSL https://ollama.com/install.sh | sh
       ollama signin
  4. Install and start the service:
       cp deploy/english-tutor-bot.service /etc/systemd/system/
       systemctl daemon-reload
       systemctl enable --now english-tutor-bot
       systemctl status english-tutor-bot

After that, pushes to main auto-deploy via GitHub Actions once you set the
DEPLOY_ENABLED variable + VPS secrets (see docs/DEPLOY.md).
NOTE
