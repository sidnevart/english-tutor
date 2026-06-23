"""Flashcard generation guards: only in-text terms, idiom tagging, dedup."""

from __future__ import annotations

from tutor.eval.flashcards import make_flashcards
from tutor.eval.schemas import Flashcard, FlashcardPayload

TEXT = (
    "The ubiquitous practice of mindfulness has gained traction lately. Many people "
    "bite the bullet and commit to daily meditation, and it often pays off handsomely."
)


class FakeLLM:
    def __init__(self, cards: list[Flashcard]) -> None:
        self._cards = cards

    async def complete(self, system: str, user: str) -> str:
        return ""

    async def complete_json(self, system, user, schema):  # noqa: ANN001
        return FlashcardPayload(cards=self._cards)


async def test_keeps_in_text_terms_drops_hallucinations_tags_idioms():
    cards = [
        Flashcard(term="ubiquitous", kind="word", definition="present everywhere"),
        Flashcard(term="bite the bullet", kind="idiom", definition="face a hardship"),
        Flashcard(term="quantum", kind="word", definition="not in the passage"),
    ]
    out = await make_flashcards(FakeLLM(cards), TEXT, limit=8)
    fronts = [c.front for c in out]

    assert "ubiquitous" in fronts
    assert "bite the bullet" in fronts
    assert "quantum" not in fronts  # not present in text -> dropped

    idiom = next(c for c in out if c.front == "bite the bullet")
    assert "idiom" in idiom.tags
    word = next(c for c in out if c.front == "ubiquitous")
    assert "present everywhere" in word.back
    assert "🇷🇺" not in word.back  # English-only cards, no translation


async def test_dedups_repeated_terms():
    cards = [Flashcard(term="ubiquitous", kind="word", definition="d") for _ in range(3)]
    out = await make_flashcards(FakeLLM(cards), TEXT, limit=8)
    assert len(out) == 1


async def test_short_text_returns_empty():
    assert await make_flashcards(FakeLLM([]), "too short", limit=8) == []


async def test_llm_error_returns_empty():
    class Boom:
        async def complete(self, s, u):
            return ""

        async def complete_json(self, s, u, schema):
            raise RuntimeError("boom")

    assert await make_flashcards(Boom(), TEXT, limit=8) == []


async def test_exclude_skips_known_terms():
    cards = [
        Flashcard(term="ubiquitous", kind="word", definition="present everywhere"),
        Flashcard(term="bite the bullet", kind="idiom", definition="face a hardship"),
    ]
    out = await make_flashcards(FakeLLM(cards), TEXT, exclude={"ubiquitous"})
    fronts = [c.front for c in out]
    assert "ubiquitous" not in fronts  # excluded as already-known
    assert "bite the bullet" in fronts


async def test_chunking_dedups_across_chunks_unlimited():
    """A long text is chunked; the same in-text term from multiple chunks dedups once."""
    # Build a >3000-char passage that contains the term in several chunks.
    sentence = "The ubiquitous compound exhibits remarkable properties in every test. "
    long_text = sentence * 80  # ~5600 chars -> 2 chunks
    assert len(long_text) > 3000

    class MultiChunkLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, system, user):  # noqa: ANN001
            return ""

        async def complete_json(self, system, user, schema):  # noqa: ANN001
            self.calls += 1
            return FlashcardPayload(
                cards=[Flashcard(term="ubiquitous", kind="word", definition="everywhere")]
            )

    llm = MultiChunkLLM()
    out = await make_flashcards(llm, long_text, limit=None)
    assert llm.calls >= 2  # multiple chunks were extracted in parallel
    assert len(out) == 1  # but the repeated term is deduped to a single card
