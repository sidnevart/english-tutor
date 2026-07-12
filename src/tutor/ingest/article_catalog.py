"""Curated catalog of high-quality article RSS feeds.

These complement Guardian API articles with longer-form, magazine-style reading
(The Conversation, AEON, Smithsonian, …) so the learner sees varied sources and
topics. The article_rss ingestor extracts the richest text each feed offers,
truncates to TOEFL-passage scale, and stores articles just like Guardian does.

Cadence is uniform (every feed is polled each refresh); variety comes from the
feeds themselves and from source rotation at delivery time. Feed list is plain
data — tune it freely.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArticleFeed:
    name: str
    url: str


CATALOG: list[ArticleFeed] = [
    # Long-form essays (science/culture/ideas) — full text fetched from the link.
    ArticleFeed("AEON", "https://aeon.co/feed.rss"),
    # Magazine articles across science/history/culture.
    ArticleFeed("Smithsonian", "https://www.smithsonianmag.com/rss/latest_articles/"),
    # General news.
    ArticleFeed("NPR", "https://feeds.npr.org/1001/rss.xml"),
]
