"""LLM access port.

The single dependency for every feature that needs a model. `complete_json`
returns a schema-validated Pydantic instance through the configured backend.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str:
        """Free-form completion for diagnostics and compatible adapters."""
        ...

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        """Structured completion validated against `schema` (with retry)."""
        ...
