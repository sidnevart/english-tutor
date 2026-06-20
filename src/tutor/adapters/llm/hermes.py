"""Sealed, optional Hermes LLM adapter.

Contract (agreed architecture):
  - `complete_json` ALWAYS runs on direct Ollama — the graded path never depends
    on Hermes.
  - `complete` (conversational) routes to Hermes behind a circuit breaker; on
    error/timeout it falls back to Ollama. After N consecutive failures the
    breaker opens and all calls go straight to Ollama until reset.

So Hermes is additive and removable: disabling it (or it failing) never breaks
the learning loop.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from tutor.config import Settings
from tutor.interfaces.llm import LLMClient

HermesComplete = Callable[[str, str], Awaitable[str]]


class HermesLLMClient:
    def __init__(
        self,
        ollama: LLMClient,
        hermes_complete: HermesComplete | None,
        *,
        failure_threshold: int = 3,
    ) -> None:
        self._ollama = ollama
        self._hermes = hermes_complete
        self._threshold = failure_threshold
        self._failures = 0
        self._open = False

    async def complete(self, system: str, user: str) -> str:
        if self._hermes is None or self._open:
            return await self._ollama.complete(system, user)
        try:
            text = await self._hermes(system, user)
            self._failures = 0
            return text
        except Exception:  # noqa: BLE001 — any failure degrades to Ollama
            self._failures += 1
            if self._failures >= self._threshold:
                self._open = True
            return await self._ollama.complete(system, user)

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        # Hard rule: structured/graded output is ALWAYS direct Ollama.
        return await self._ollama.complete_json(system, user, schema)


def make_openai_complete(base_url: str, api_key: str, model: str) -> HermesComplete:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key or "hermes")

    async def _complete(system: str, user: str) -> str:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=30,
        )
        return resp.choices[0].message.content or ""

    return _complete


def build_hermes_client(settings: Settings) -> HermesLLMClient:
    from tutor.adapters.llm.ollama import OllamaLLMClient

    ollama = OllamaLLMClient(
        settings.ollama_base_url, settings.ollama_api_key, settings.ollama_model
    )
    hermes_complete: HermesComplete | None = None
    if settings.hermes_enabled and settings.hermes_base_url:
        hermes_complete = make_openai_complete(
            settings.hermes_base_url,
            settings.hermes_api_key,
            settings.hermes_model or settings.ollama_model,
        )
    return HermesLLMClient(ollama, hermes_complete)
