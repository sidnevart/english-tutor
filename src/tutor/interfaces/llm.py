"""LLM access port.

The single dependency for every feature that needs a model. `complete_json`
returns a validated pydantic instance and, by contract, ALWAYS runs on direct
Ollama (even inside the optional Hermes adapter), keeping the graded path
deterministic.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str:
        """Free-form completion (conversational)."""
        ...

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        """Structured completion validated against `schema` (with retry)."""
        ...
