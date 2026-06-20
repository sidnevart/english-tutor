"""Default Anki sink: write a .apkg deck file (headless-VPS safe).

Deck ids are derived from the deck name and note GUIDs from field content, so
re-exporting and re-importing is idempotent in Anki.
"""

from __future__ import annotations

import hashlib
import re
import zlib
from pathlib import Path

import genanki

from tutor.domain.models import AnkiResult, Card

_MODEL_ID = 1607392319  # fixed, stable across runs
_MODEL = genanki.Model(
    _MODEL_ID,
    "TOEFL Basic",
    fields=[{"name": "Front"}, {"name": "Back"}],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Front}}",
            "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
        }
    ],
)


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower() or "deck"


class GenankiSink:
    def __init__(self, out_dir: str | Path) -> None:
        self._out = Path(out_dir)

    async def health(self) -> bool:
        return True

    async def add_cards(self, deck: str, cards: list[Card]) -> AnkiResult:
        deck_id = zlib.crc32(deck.encode("utf-8")) | 1
        gdeck = genanki.Deck(deck_id, deck)
        for c in cards:
            note = genanki.Note(
                model=_MODEL,
                fields=[c.front, c.back.replace("\n", "<br>")],
                tags=[t.replace(" ", "_") for t in c.tags],
            )
            gdeck.add_note(note)

        self._out.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1("|".join(c.front for c in cards).encode("utf-8")).hexdigest()[:8]
        path = self._out / f"{_slug(deck)}-{digest}.apkg"
        genanki.Package(gdeck).write_to_file(str(path))
        return AnkiResult(sink="genanki", deck=deck, count=len(cards), apkg_path=str(path))
