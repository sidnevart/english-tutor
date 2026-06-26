"""MiMo LLM adapter — Anthropic-compatible endpoint via httpx.

Used when LLM_BACKEND=mimo. Calls the Anthropic Messages API directly using
httpx (already a project dependency) so we don't need the `anthropic` package.
"""

from __future__ import annotations

import json

import httpx
from pydantic import BaseModel


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


class MiMoLLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, retries: int = 2) -> None:
        # Ensure base_url doesn't end with /v1 (we add /v1/messages ourselves).
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._retries = retries

    async def _messages(self, system: str, user: str, max_tokens: int = 4096) -> str:
        """Call the Anthropic Messages API and return the text content."""
        url = f"{self._base}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": self._model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
        data = resp.json()
        # Anthropic response: {content: [{type: "text", text: "..."}]}
        parts = data.get("content", [])
        return "".join(p.get("text", "") for p in parts if p.get("type") == "text")

    async def complete(self, system: str, user: str) -> str:
        return await self._messages(system, user)

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        instruction = (
            "Respond with ONLY a single valid JSON object matching this JSON "
            f"schema (no prose, no code fences):\n{json.dumps(schema.model_json_schema())}"
        )
        last_err: Exception | None = None
        for _ in range(self._retries + 1):
            content = await self._messages(f"{system}\n\n{instruction}", user)
            try:
                return schema.model_validate_json(_extract_json(content))
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise RuntimeError(f"LLM did not return valid {schema.__name__}: {last_err}")