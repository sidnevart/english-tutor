"""Podcast catalog + delivery cadence, encoded as data.

Cadence rules:
  - Daily Core: Short Wave, The Indicator, TED Tech  (8-33 min)
  - 3x/week (Mon/Wed/Fri): Planet Money, NPR Up First  (12-34 min)
  - Weekend: BBC 6 Minute English, Consider This (NPR)  (6-28 min)

All feeds are empirically verified to produce episodes under 40 min.
Feed URLs can be corrected by running `tutor ingest` and checking the output.
"""

from __future__ import annotations

from dataclasses import dataclass

from tutor.domain.enums import Cadence

# Monday=0 .. Sunday=6
_THRICE_DAYS = frozenset({0, 2, 4})
_WEEKEND_DAYS = frozenset({5, 6})


@dataclass(frozen=True)
class Podcast:
    name: str
    feed_url: str
    cadence: Cadence


CATALOG: list[Podcast] = [
    # Daily core — 8-33 min per episode
    Podcast("Short Wave", "https://feeds.npr.org/510351/podcast.xml", Cadence.DAILY),
    Podcast("The Indicator", "https://feeds.npr.org/510325/podcast.xml", Cadence.DAILY),
    Podcast("TED Tech", "https://feeds.megaphone.fm/VMP5705694065", Cadence.DAILY),
    # 3x / week (Mon/Wed/Fri) — 12-34 min per episode
    Podcast("Planet Money", "https://feeds.npr.org/510289/podcast.xml", Cadence.THRICE),
    Podcast("NPR Up First", "https://feeds.npr.org/510318/podcast.xml", Cadence.THRICE),
    # Weekend — 6-28 min per episode
    Podcast(
        "BBC 6 Minute English",
        "https://podcasts.files.bbci.co.uk/p02pc9pj.rss",
        Cadence.WEEKEND,
    ),
    Podcast("Consider This (NPR)", "https://feeds.npr.org/510355/podcast.xml", Cadence.WEEKEND),
]


def due_today(weekday: int) -> list[Podcast]:
    """Podcasts scheduled for the given weekday (Mon=0 .. Sun=6)."""
    due = [p for p in CATALOG if p.cadence == Cadence.DAILY]
    if weekday in _THRICE_DAYS:
        due += [p for p in CATALOG if p.cadence == Cadence.THRICE]
    if weekday in _WEEKEND_DAYS:
        due += [p for p in CATALOG if p.cadence == Cadence.WEEKEND]
    return due
