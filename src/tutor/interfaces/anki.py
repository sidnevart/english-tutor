"""Anki sink port. Default impl writes .apkg (headless-safe); AnkiConnect is
opportunistic when an Anki desktop is reachable."""

from __future__ import annotations

from typing import Protocol

from tutor.domain.models import AnkiResult, Card


class AnkiSink(Protocol):
    async def health(self) -> bool:
        """Whether this sink can currently accept cards."""
        ...

    async def add_cards(self, deck: str, cards: list[Card]) -> AnkiResult: ...
