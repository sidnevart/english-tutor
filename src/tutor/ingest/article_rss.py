"""Article ingestion from curated RSS feeds (magazine-quality reading).

Unlike the podcast RSS ingest (`rss.py`), this stores ARTICLES: it pulls the
richest text a feed offers (full content > summary), strips HTML, and truncates
to TOEFL-passage scale. Long articles are TRUNCATED rather than dropped (a
cap that discards every long-form piece would starve the queue); only genuinely
short items (blurbs/ads) are filtered out.

Stored with `source_type=RSS`, `source_ref=<feed name>` so it dedups against
Guardian and rotates cleanly at delivery time.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import UTC, datetime
from typing import Any

import feedparser

from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.article_catalog import CATALOG

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?)\"])")


def _strip_html(raw: str) -> str:
    """Drop HTML tags, collapse whitespace, and tidy spaces before punctuation."""
    without_tags = _TAG_RE.sub(" ", raw)
    text = _WS_RE.sub(" ", html_lib.unescape(without_tags)).strip()
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def _best_text(entry: Any) -> str:
    """Pick the richest text an entry carries: full content > summary."""
    content = entry.get("content") or []
    if content and isinstance(content, list):
        first = content[0]
        value = first.get("value", "") if isinstance(first, dict) else getattr(first, "value", "")
        if value:
            return _strip_html(value)
    return _strip_html(entry.get("summary", "") or "")


def _truncate(text: str, max_chars: int) -> str:
    """Cut to at most `max_chars` on a sentence boundary when possible."""
    if len(text) <= max_chars:
        return text
    chunk = text[:max_chars]
    # Prefer to end on a sentence; fall back to a word boundary.
    for sep in (". ", "? ", "! "):
        at = chunk.rfind(sep)
        if at > max_chars * 0.6:
            return chunk[: at + 1].strip()
    return chunk.rsplit(" ", 1)[0].strip()


def _published(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def normalize_entry(
    entry: Any, feed_name: str, *, min_chars: int, max_chars: int
) -> RawItem | None:
    """Convert a feed entry to an article RawItem, or None if it has no real body.

    Long bodies are truncated to `max_chars`; bodies shorter than `min_chars`
    (blurbs/ads) are dropped."""
    title = (entry.get("title") or "").strip()
    body = _best_text(entry)
    if not title or len(body) < min_chars:
        return None
    body = _truncate(body, max_chars)
    external = entry.get("id") or entry.get("guid") or entry.get("link") or title
    return RawItem(
        source_type=SourceType.RSS,
        source_ref=feed_name,
        external_id=str(external),
        content_type=ContentType.ARTICLE,
        title=title[:120],
        url=entry.get("link", ""),
        body_text=body,
        published_at=_published(entry),
    )


async def run_article_rss_ingest(
    settings: Settings, repo: Repository, limit_per_feed: int = 2
) -> dict[str, int]:
    """Ingest up to `limit_per_feed` new articles per curated feed.

    Returns per-feed counts of newly stored articles. Feed fetch errors are
    logged via the repo and never abort the whole run."""
    counts: dict[str, int] = {}
    for feed in CATALOG:
        stored = 0
        try:
            parsed = feedparser.parse(feed.url)
            for entry in (parsed.entries or [])[:limit_per_feed]:
                raw = normalize_entry(
                    entry,
                    feed.name,
                    min_chars=settings.min_article_len,
                    max_chars=settings.max_article_len,
                )
                if raw is None:
                    continue
                if repo.add_content(raw, settings.admin_user_id) is not None:
                    stored += 1
                    if stored >= limit_per_feed:
                        break
        except Exception as exc:  # noqa: BLE001 - one bad feed must not kill the run
            repo.log_job("article_rss", "error", f"{feed.name}: {exc}")
        counts[feed.name] = stored
    return counts
