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

# 3. Install runtime dependencies.
"$UV" sync

# Groq TTS transcodes WAV output to Telegram-compatible OGG/Opus.
if ! command -v ffmpeg >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ffmpeg
fi

cat <<'NOTE'

✅ Code + deps installed.

One-time manual steps (secrets are intentionally NOT in git):

  1. Create /opt/english-tutor/.env from .env.example and fill at least:
       BOT_TOKEN, ADMIN_USER_ID, NOTIFIER_BACKEND=telegram,
       LLM_BACKEND=ollama, STT_BACKEND=cloud, TTS_BACKEND=groq
  2. Install Ollama and sign in (glm-5:cloud is cloud-routed):
       curl -fsSL https://ollama.com/install.sh | sh
       ollama signin
  3. Install and start the service:
       cp deploy/english-tutor-bot.service /etc/systemd/system/
       systemctl daemon-reload
       systemctl enable --now english-tutor-bot
       systemctl status english-tutor-bot

After that, pushes to main auto-deploy via GitHub Actions once you set the
DEPLOY_ENABLED variable + VPS secrets (see docs/DEPLOY.md).
NOTE
