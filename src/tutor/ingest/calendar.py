"""Podcast catalog + delivery cadence, encoded as data.

Cadence rules from the brief:
  - Daily Core: Short Wave, The Indicator, TED Tech
  - 3x/week (Mon/Wed/Fri): Hidden Brain, Planet Money, Freakonomics
  - Weekend: Latent Space, Software Engineering Daily, Acquired, Beyond Coding

Feed URLs are best-known defaults; they are validated empirically by running
`tutor ingest` and can be corrected here.
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
    # Daily core
    Podcast("Short Wave", "https://feeds.npr.org/510351/podcast.xml", Cadence.DAILY),
    Podcast("The Indicator", "https://feeds.npr.org/510325/podcast.xml", Cadence.DAILY),
    Podcast("TED Tech", "https://feeds.megaphone.fm/VMP5705694065", Cadence.DAILY),
    # 3x / week
    Podcast("Hidden Brain", "https://feeds.simplecast.com/kwWc0lhf", Cadence.THRICE),
    Podcast("Planet Money", "https://feeds.npr.org/510289/podcast.xml", Cadence.THRICE),
    Podcast("Freakonomics Radio", "https://feeds.simplecast.com/Y8lFbOT4", Cadence.THRICE),
    # Weekend deep mode
    Podcast("Latent Space", "https://api.substack.com/feed/podcast/1084089.rss", Cadence.WEEKEND),
    Podcast(
        "Software Engineering Daily",
        "https://softwareengineeringdaily.com/feed/podcast/",
        Cadence.WEEKEND,
    ),
    Podcast("Acquired", "https://feeds.transistor.fm/acquired", Cadence.WEEKEND),
    Podcast(
        "Beyond Coding",
        "https://anchor.fm/s/5bb57eac/podcast/rss",
        Cadence.WEEKEND,
    ),
]


def due_today(weekday: int) -> list[Podcast]:
    """Podcasts scheduled for the given weekday (Mon=0 .. Sun=6)."""
    due = [p for p in CATALOG if p.cadence == Cadence.DAILY]
    if weekday in _THRICE_DAYS:
        due += [p for p in CATALOG if p.cadence == Cadence.THRICE]
    if weekday in _WEEKEND_DAYS:
        due += [p for p in CATALOG if p.cadence == Cadence.WEEKEND]
    return due
