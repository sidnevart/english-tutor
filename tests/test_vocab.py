"""Deterministic vocab selection: only in-text, rarer words, rarest first."""

from __future__ import annotations

import re

from tutor.eval.vocab import select_vocab

TEXT = (
    "The ubiquitous and ephemeral nature of quotidian routines often belies "
    "their importance. People overlook serendipitous moments while chasing "
    "the next thing."
)


def test_selects_in_text_rare_words_and_drops_common():
    items = select_vocab(content_id=1, text=TEXT, limit=8)
    words = {v.word for v in items}

    assert "ubiquitous" in words
    assert "ephemeral" in words
    # very common words are filtered out by the frequency band / stoplist
    assert "the" not in words
    assert "and" not in words
    assert "their" not in words


def test_every_selected_word_is_present_in_text():
    items = select_vocab(content_id=1, text=TEXT, limit=8)
    for v in items:
        assert re.search(rf"\b{re.escape(v.word)}\b", TEXT, flags=re.IGNORECASE)


def test_rarest_first_and_respects_limit():
    items = select_vocab(content_id=1, text=TEXT, limit=3)
    assert len(items) <= 3
    ranks = [v.freq_rank for v in items]
    assert ranks == sorted(ranks)  # ascending zipf = rarer first
