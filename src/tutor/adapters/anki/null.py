"""No-op Anki sink (keeps the loop alive when card export is disabled)."""

from __future__ import annotations

from tutor.domain.models import AnkiResult, Card


class NullSink:
    async def health(self) -> bool:
        return True

    async def add_cards(self, deck: str, cards: list[Card]) -> AnkiResult:
        return AnkiResult(sink="null", deck=deck, count=0)
