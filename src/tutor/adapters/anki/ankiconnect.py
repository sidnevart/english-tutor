"""Opportunistic Anki sink via the AnkiConnect addon (requires Anki desktop).

Used only when `health()` confirms the endpoint answers; otherwise the factory
falls back to the .apkg sink.
"""

from __future__ import annotations

import httpx

from tutor.domain.models import AnkiResult, Card


class AnkiConnectSink:
    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout

    async def _invoke(self, action: str, **params: object) -> object:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                self._url, json={"action": action, "version": 6, "params": params}
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise RuntimeError(data["error"])
            return data.get("result")

    async def health(self) -> bool:
        try:
            await self._invoke("version")
            return True
        except Exception:  # noqa: BLE001
            return False

    async def add_cards(self, deck: str, cards: list[Card]) -> AnkiResult:
        await self._invoke("createDeck", deck=deck)
        notes = [
            {
                "deckName": deck,
                "modelName": "Basic",
                "fields": {"Front": c.front, "Back": c.back.replace("\n", "<br>")},
                "tags": c.tags,
                "options": {"allowDuplicate": False},
            }
            for c in cards
        ]
        result = await self._invoke("addNotes", notes=notes)
        note_ids = [int(i) for i in (result or []) if i]
        return AnkiResult(sink="ankiconnect", deck=deck, count=len(note_ids), note_ids=note_ids)
