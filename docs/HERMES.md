# Optional Hermes voice/chat plane

Hermes Agent (Nous Research) is **optional and sealed**: it is never on the
graded path. Structured quiz generation (`complete_json`) **always** runs on
direct Ollama, even when `LLM_BACKEND=hermes`. Hermes only handles free-form
*conversational* turns, behind a circuit breaker that falls back to Ollama on
any error. Disabling Hermes (or it failing) never breaks the learning loop.

There are two independent ways to use it.

## A. Conversational completions inside this bot (lightweight)

Point our `complete()` calls at a Hermes (or any OpenAI-compatible) endpoint.
This powers `/coach` and voice replies.

```ini
# .env
LLM_BACKEND=hermes
HERMES_ENABLED=true
HERMES_BASE_URL=http://127.0.0.1:8080/v1   # your Hermes / OpenAI-compatible endpoint
HERMES_MODEL=                              # blank -> falls back to OLLAMA_MODEL
HERMES_API_KEY=
```

If `HERMES_ENABLED` is false or `HERMES_BASE_URL` is empty, `complete()` simply
uses Ollama — so `LLM_BACKEND=hermes` is always safe.

## B. Hermes's own Telegram gateway (heavy, full agent + built-in voice STT/TTS)

Run the real Hermes agent as a **separate** process for rich voice/chat
practice. It brings its own faster-whisper STT and Edge-TTS.

```bash
# 1. Install Hermes (see https://github.com/NousResearch/hermes-agent)
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 2. Persona: use the tutor voice
mkdir -p ~/.hermes && cp hermes/SOUL.md ~/.hermes/SOUL.md

# 3. Point Hermes at local Ollama (custom endpoint)
#    base_url: http://127.0.0.1:11434/v1   model: glm-5:cloud   (api key blank)

# 4. Configure its Telegram gateway (its own bot token + your user id)
#    then run:
hermes gateway
```

This is a second bot, distinct from `tutor bot`. Keep it optional: the core
TOEFL loop runs fully without it.
