"""RSS podcast ingestion (feedparser).

Episodes are stored lazily: only metadata + the audio enclosure URL are saved
now; transcription happens later, when an episode is actually evaluated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import feedparser

from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.calendar import Podcast, due_today


def _enclosure_url(entry: Any) -> str:
    for enc in entry.get("enclosures", []) or []:
        href = enc.get("href", "") if isinstance(enc, dict) else getattr(enc, "href", "")
        if href:
            return href
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and link.get("href"):
            return link["href"]
    return ""


def _duration_sec(entry: Any) -> int | None:
    raw = entry.get("itunes_duration")
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        if ":" in raw:
            parts = [int(p) for p in raw.split(":")]
            secs = 0
            for p in parts:
                secs = secs * 60 + p
            return secs
        return int(raw)
    except ValueError:
        return None


def _published(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def normalize_entry(entry: Any, podcast: Podcast) -> RawItem | None:
    """Convert a feed entry to a RawItem, or None if it lacks title/audio."""
    title = (entry.get("title") or "").strip()
    audio = _enclosure_url(entry)
    if not title or not audio:
        return None
    external = entry.get("id") or entry.get("guid") or entry.get("link") or title
    return RawItem(
        source_type=SourceType.RSS,
        source_ref=podcast.name,
        external_id=str(external),
        content_type=ContentType.PODCAST,
        title=title[:120],
        url=entry.get("link", ""),
        body_text="",  # filled lazily on transcription
        audio_url=audio,
        duration_sec=_duration_sec(entry),
        cadence_bucket=podcast.cadence,
        published_at=_published(entry),
    )


def _weekday(settings: Settings) -> int:
    return datetime.now(ZoneInfo(settings.tz)).weekday()


async def run_ingest(
    settings: Settings, repo: Repository, limit_per_feed: int = 1
) -> dict[str, int]:
    """Ingest the latest episode(s) of every podcast due today. Returns
    per-podcast counts of newly stored episodes."""
    counts: dict[str, int] = {}
    for podcast in due_today(_weekday(settings)):
        parsed = feedparser.parse(podcast.feed_url)
        stored = 0
        for entry in (parsed.entries or [])[:limit_per_feed]:
            raw = normalize_entry(entry, podcast)
            if raw and repo.add_content(raw, settings.admin_user_id) is not None:
                stored += 1
        counts[podcast.name] = stored
    return counts
