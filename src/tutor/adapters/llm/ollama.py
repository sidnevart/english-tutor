"""Real LLM via Ollama's OpenAI-compatible endpoint.

`complete_json` requests JSON output, then validates against the schema with a
small retry budget so a malformed response is rejected rather than propagated.
"""

from __future__ import annotations

import json

from openai import AsyncOpenAI
from pydantic import BaseModel


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    return text.strip()


class OllamaLLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, retries: int = 2) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key or "ollama")
        self._model = model
        self._retries = retries

    async def complete(self, system: str, user: str) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        instruction = (
            "Respond with ONLY a single valid JSON object matching this JSON "
            f"schema (no prose, no code fences):\n{json.dumps(schema.model_json_schema())}"
        )
        last_err: Exception | None = None
        for _ in range(self._retries + 1):
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": f"{system}\n\n{instruction}"},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
            content = resp.choices[0].message.content or ""
            try:
                return schema.model_validate_json(_extract_json(content))
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise RuntimeError(f"LLM did not return valid {schema.__name__}: {last_err}")
