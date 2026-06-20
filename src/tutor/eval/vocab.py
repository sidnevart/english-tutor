"""Deterministic vocabulary selection.

No LLM: tokenize the passage, score each candidate by Zipf frequency
(``wordfreq``), and keep the mid/low-frequency words that are ACTUALLY present
in the text. This guarantees the spec's "exact words from the day's text" and
makes the step fast and reproducible. (Definitions can later be glossed by a
real LLM; the selection itself never depends on one.)
"""

from __future__ import annotations

import re

from wordfreq import zipf_frequency

from tutor.domain.models import VocabItem

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")

# A tiny stoplist of common-but-long words that slip past the frequency filter.
_STOP = frozenset(
    {
        "about",
        "above",
        "after",
        "again",
        "against",
        "because",
        "before",
        "being",
        "between",
        "could",
        "during",
        "their",
        "there",
        "these",
        "those",
        "through",
        "under",
        "until",
        "where",
        "which",
        "while",
        "would",
        "should",
        "people",
        "really",
        "things",
        "something",
    }
)

# Zipf scale: ~7 = "the", ~3 = moderately common, <2 = rare/noise.
DEFAULT_MIN_ZIPF = 1.5
DEFAULT_MAX_ZIPF = 4.5


def _present_in(word: str, text: str) -> bool:
    """Whole-word, case-insensitive presence check (drops hallucinations)."""
    return re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE) is not None


def select_vocab(
    content_id: int,
    text: str,
    *,
    limit: int = 8,
    min_zipf: float = DEFAULT_MIN_ZIPF,
    max_zipf: float = DEFAULT_MAX_ZIPF,
    min_len: int = 4,
) -> list[VocabItem]:
    """Pick up to `limit` rarer words from `text`, rarest first."""
    seen: dict[str, float] = {}
    for match in _WORD.finditer(text):
        word = match.group(0).lower().strip("'-")
        if len(word) < min_len or word in _STOP or word in seen:
            continue
        zipf = zipf_frequency(word, "en")
        if min_zipf <= zipf <= max_zipf and _present_in(word, text):
            seen[word] = zipf

    ranked = sorted(seen.items(), key=lambda kv: kv[1])  # rarer (lower zipf) first
    return [
        VocabItem(content_id=content_id, word=word, freq_rank=zipf) for word, zipf in ranked[:limit]
    ]
