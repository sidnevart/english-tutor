"""Fallback LLM client: tries the primary first, falls back to secondary on error.

Used for `LLM_BACKEND=ollama_mimo` — tries Ollama, and if it's down or times
out, transparently retries with MiMo.  Both calls share the same interface so
the rest of the codebase never knows which backend answered.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from tutor.interfaces.llm import LLMClient

_log = logging.getLogger(__name__)


class FallbackLLMClient:
    """Try `primary` first; on any exception, log a warning and try `fallback`."""

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self._primary = primary
        self._fallback = fallback

    async def complete(self, system: str, user: str) -> str:
        try:
            return await self._primary.complete(system, user)
        except Exception as exc:
            _log.warning("Primary LLM failed (%s), falling back to secondary: %s",
                         type(exc).__name__, exc)
            return await self._fallback.complete(system, user)

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        try:
            return await self._primary.complete_json(system, user, schema)
        except Exception as exc:
            _log.warning("Primary LLM failed (%s), falling back to secondary: %s",
                         type(exc).__name__, exc)
            return await self._fallback.complete_json(system, user, schema)