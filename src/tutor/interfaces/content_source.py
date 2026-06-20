"""Content ingestion port — channel scraper and RSS source implement this."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from tutor.domain.models import RawItem


class ContentSource(Protocol):
    async def fetch(self, since: datetime | None = None) -> list[RawItem]: ...
