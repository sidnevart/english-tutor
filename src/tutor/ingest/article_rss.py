"""Article ingestion from curated RSS feeds (magazine-quality reading).

Unlike the podcast RSS ingest (`rss.py`), this stores ARTICLES. Many quality
feeds (AEON, Smithsonian, NPR) only publish a short teaser in RSS — the visible
text is well under TOEFL scale even though the raw field looks long (it's
inflated by markup/URLs). So when a feed's own text is too short, we fetch the
article's link and extract the full body with `trafilatura`. That makes any
feed deliver real reading material.

Stored with `source_type=RSS`, `source_ref=<feed name>` so it dedups against
Guardian and rotates cleanly at delivery time.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Callable
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


_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _extract_url(url: str) -> str:
    """Fetch a page (browser User-Agent — many sites block the default) and
    return its main article text via trafilatura. "" on any failure."""
    import trafilatura

    downloaded = trafilatura.fetch_url(url, no_ssl=False)
    if not downloaded:
        # Fall back to httpx with a browser UA for sites that block the default.
        try:
            import httpx

            resp = httpx.get(
                url, timeout=20, follow_redirects=True, headers={"User-Agent": _BROWSER_UA}
            )
            resp.raise_for_status()
            downloaded = resp.text
        except Exception:  # noqa: BLE001
            return ""
    return trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""


def normalize_entry(
    entry: Any, feed_name: str, *, min_chars: int, max_chars: int
) -> RawItem | None:
    """Convert a feed entry to an article RawItem using the feed's own text, or
    None if that text is too short (a teaser). Long bodies are truncated."""
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


def raw_from_url(
    entry: Any,
    feed_name: str,
    *,
    min_chars: int,
    max_chars: int,
    fetch: Callable[[str], str] = _extract_url,
) -> RawItem | None:
    """Fallback for teaser-only feeds: fetch the entry's link and extract the
    full article text. Returns None if there's no link or the extraction is too
    short. `fetch` is injectable so tests avoid the network."""
    url = (entry.get("link") or "").strip()
    if not url:
        return None
    try:
        body = fetch(url)
    except Exception:  # noqa: BLE001 - a bad link must not abort the run
        return None
    if not body or len(body) < min_chars:
        return None
    title = (entry.get("title") or "").strip() or url
    external = entry.get("id") or entry.get("guid") or url
    return RawItem(
        source_type=SourceType.RSS,
        source_ref=feed_name,
        external_id=str(external),
        content_type=ContentType.ARTICLE,
        title=title[:120],
        url=url,
        body_text=_truncate(body, max_chars),
        published_at=_published(entry),
    )


async def run_article_rss_ingest(
    settings: Settings, repo: Repository, limit_per_feed: int = 2
) -> dict[str, int]:
    """Ingest up to `limit_per_feed` new articles per curated feed.

    For each entry we first try the feed's own text; if it's just a teaser we
    fetch the full article from the link. Returns per-feed counts of newly
    stored articles. Errors are logged and never abort the whole run."""
    counts: dict[str, int] = {}
    for feed in CATALOG:
        stored = 0
        try:
            parsed = feedparser.parse(feed.url)
            for entry in (parsed.entries or [])[: limit_per_feed * 3]:
                raw = normalize_entry(
                    entry,
                    feed.name,
                    min_chars=settings.min_article_len,
                    max_chars=settings.max_article_len,
                )
                if raw is None:
                    raw = raw_from_url(
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
