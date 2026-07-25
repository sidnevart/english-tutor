"""Domain models — the data that flows between adapters."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Card(BaseModel):
    """An Anki note to be written by an AnkiSink."""

    front: str
    back: str
    tags: list[str] = Field(default_factory=list)


class AnkiResult(BaseModel):
    sink: str
    deck: str
    count: int
    apkg_path: str | None = None
    note_ids: list[int] = Field(default_factory=list)
