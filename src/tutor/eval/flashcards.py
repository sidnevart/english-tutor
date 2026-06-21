"""LLM-generated Anki flashcards: TOEFL words & idioms from a passage.

Runs through `complete_json` (always direct Ollama, validated). Every term is
re-verified to actually occur in the source text, so hallucinated entries are
dropped — the cards are guaranteed to be "from the day's text".

Card shape: front = the term; back = English definition + example + 🇷🇺 RU.
"""

from __future__ import annotations

import re

from tutor.domain.models import Card
from tutor.eval.schemas import FlashcardPayload
from tutor.interfaces.llm import LLMClient

_SYSTEM = (
    "You are a TOEFL vocabulary coach building Anki flashcards for a "
    "Russian-speaking learner. From the passage, pick the most useful TOEFL-level "
    "vocabulary WORDS and IDIOMS / fixed expressions that ACTUALLY APPEAR in the "
    "text. Skip trivial or very common words. For each item give: the term exactly "
    "as it appears; kind ('word' or 'idiom'); a concise English definition; a "
    "natural example sentence; and an accurate Russian translation."
)


def _present(term: str, text: str) -> bool:
    term = term.strip()
    if not term:
        return False
    if " " in term:  # idiom / phrase — substring match is enough
        return term.lower() in text.lower()
    return re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE) is not None


async def make_flashcards(llm: LLMClient, text: str, *, limit: int = 8) -> list[Card]:
    text = text.strip()
    if len(text) < 100:
        return []
    user = f"Create up to {limit} flashcards from this passage.\n\nPASSAGE:\n{text}"
    try:
        payload = await llm.complete_json(_SYSTEM, user, FlashcardPayload)
    except Exception:  # noqa: BLE001 — cards are best-effort, never block delivery
        return []

    cards: list[Card] = []
    seen: set[str] = set()
    for fc in payload.cards:
        term = fc.term.strip()
        key = term.lower()
        if not term or key in seen or not _present(term, text):
            continue
        seen.add(key)
        back = fc.definition.strip()
        if fc.example.strip():
            back += f"\n\n<i>{fc.example.strip()}</i>"
        if fc.translation.strip():
            back += f"\n\n🇷🇺 {fc.translation.strip()}"
        tag = "idiom" if fc.kind.strip().lower() == "idiom" else "vocab"
        cards.append(Card(front=term, back=back, tags=["toefl", tag]))
        if len(cards) >= limit:
            break
    return cards
