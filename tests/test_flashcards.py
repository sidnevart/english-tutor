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
        Flashcard(
            term="ubiquitous",
            kind="word",
            definition="present everywhere",
            translation="вездесущий",
        ),
        Flashcard(
            term="bite the bullet",
            kind="idiom",
            definition="face a hardship",
            translation="стиснуть зубы",
        ),
        Flashcard(
            term="quantum", kind="word", definition="not in the passage", translation="квант"
        ),
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
    assert "вездесущий" in word.back  # Russian translation on the back


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
