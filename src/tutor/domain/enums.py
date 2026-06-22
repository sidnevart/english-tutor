"""Enumerations and the content delivery state machine.

The state machine is defined once here and enforced in two places:
  1. `repository.py` (Python guard, raises `InvalidTransition`)
  2. a SQLite `BEFORE UPDATE` trigger (defense-in-depth, `RAISE(ABORT)`)
so a buggy or rogue caller can never corrupt content state.
"""

from __future__ import annotations

from enum import StrEnum


class DeliveryStatus(StrEnum):
    NEW = "NEW"
    DELIVERED = "DELIVERED"
    REVIEWED = "REVIEWED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class ContentType(StrEnum):
    ARTICLE = "article"
    PODCAST = "podcast"


class SourceType(StrEnum):
    CHANNEL = "channel"
    RSS = "rss"


class Cadence(StrEnum):
    DAILY = "daily"
    THRICE = "thrice"
    WEEKEND = "weekend"


class QuizKind(StrEnum):
    READING = "reading"
    LISTENING = "listening"
    VOCAB = "vocab"


# The single source of truth for legal status transitions.
LEGAL_TRANSITIONS: dict[DeliveryStatus, frozenset[DeliveryStatus]] = {
    DeliveryStatus.NEW: frozenset(
        {DeliveryStatus.DELIVERED, DeliveryStatus.SKIPPED, DeliveryStatus.FAILED}
    ),
    DeliveryStatus.DELIVERED: frozenset(
        {DeliveryStatus.REVIEWED, DeliveryStatus.SKIPPED, DeliveryStatus.FAILED}
    ),
    DeliveryStatus.REVIEWED: frozenset(),  # terminal
    DeliveryStatus.SKIPPED: frozenset({DeliveryStatus.NEW}),  # re-queue
    DeliveryStatus.FAILED: frozenset({DeliveryStatus.NEW}),  # retry
}


def is_legal_transition(src: DeliveryStatus, dst: DeliveryStatus) -> bool:
    """Whether moving from `src` to `dst` is allowed (a no-op move is legal)."""
    if src == dst:
        return True
    return dst in LEGAL_TRANSITIONS.get(src, frozenset())
