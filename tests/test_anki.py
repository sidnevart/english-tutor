"""Anki sinks: genanki writes a valid .apkg; null is a no-op."""

from __future__ import annotations

import zipfile

from tutor.adapters.anki.genanki_sink import GenankiSink
from tutor.adapters.anki.null import NullSink
from tutor.domain.models import Card

CARDS = [
    Card(front="ubiquitous", back="present everywhere", tags=["toefl", "vocab"]),
    Card(front="ephemeral", back="short-lived", tags=["toefl", "vocab"]),
]


async def test_genanki_writes_valid_apkg(tmp_path):
    sink = GenankiSink(tmp_path)
    result = await sink.add_cards("TOEFL::Daily", CARDS)

    assert result.sink == "genanki"
    assert result.count == 2
    assert result.apkg_path is not None and result.apkg_path.endswith(".apkg")

    assert zipfile.is_zipfile(result.apkg_path)
    with zipfile.ZipFile(result.apkg_path) as zf:
        # an .apkg is a zip containing the Anki collection sqlite db
        assert any(n.startswith("collection.anki2") for n in zf.namelist())


async def test_null_sink_is_noop():
    result = await NullSink().add_cards("TOEFL::Daily", CARDS)
    assert result.count == 0
    assert result.apkg_path is None
