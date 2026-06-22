"""LLM-generated Anki flashcards from a passage.

Extracts ALL useful language items: vocabulary, phrasal verbs, collocations,
idioms, and academic phrases. Every term is re-verified to actually occur in
the source text, so hallucinated entries are dropped.

Card shape: front = the term; back = English definition + example + RU translation.
"""

from __future__ import annotations

import re

from tutor.domain.models import Card
from tutor.eval.schemas import FlashcardPayload
from tutor.interfaces.llm import LLMClient

_SYSTEM = (
    "You are a TOEFL vocabulary coach building English Anki flashcards for a "
    "B2-C1 Russian-speaking learner. Your job is to extract ALL useful language "
    "items from the passage — be exhaustive, not selective.\n\n"
    "SCAN THE PASSAGE FOR:\n"
    "1. Academic vocabulary words (Zipf 3-6) — nouns, verbs, adjectives that "
    "   a B2-C1 learner might not know or might misuse\n"
    "2. Phrasal verbs — e.g., 'carry out', 'bring about', 'phase out', "
    "   'stem from', 'give rise to', 'account for'\n"
    "3. Collocations — words that naturally go together: 'conduct research', "
    "   'pose a threat', 'draw conclusions', 'reach a consensus', 'shed light on'\n"
    "4. Idioms and fixed expressions — 'on the other hand', 'it turns out', "
    "   'by virtue of', 'in the wake of', 'to shed light on'\n"
    "5. Useful TOEFL writing phrases — 'it is worth noting that', 'this lends "
    "   credence to', 'a growing body of evidence', 'to a certain extent'\n"
    "6. Adjective + noun combinations — 'compelling evidence', 'profound impact', "
    "   'rigorous methodology', 'unprecedented growth'\n"
    "7. Verb + noun combinations — 'undergo transformation', 'yield results', "
    "   'pose a challenge', 'reach a conclusion'\n\n"
    "EXTRACTION RULES:\n"
    "- Extract EVERY item you find — aim for the maximum. Do not stop early.\n"
    "- Start with the most important terms: key concepts, central vocabulary, "
    "  and named phenomena from the passage (e.g., 'Neolithic Revolution', "
    "  'thermohaline circulation', 'constructive model'). These are MUST-HAVE.\n"
    "- Then add mid-frequency academic words, phrasal verbs, collocations.\n"
    "- Each term must appear EXACTLY as written in the passage.\n"
    "- Include multi-word expressions as single cards (e.g., 'give rise to').\n"
    "- For each item provide: the exact term, kind (word/phrasal_verb/"
    "  collocation/idiom/phrase), a concise English definition, a natural "
    "  example sentence, and a Russian translation.\n"
    "- Everything must be in English except the Russian translation."
)


def _present(term: str, text: str) -> bool:
    """Check that the term actually appears in the source text."""
    term = term.strip()
    if not term:
        return False
    if " " in term:  # multi-word — substring match
        return term.lower() in text.lower()
    return re.search(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE) is not None


async def make_flashcards(llm: LLMClient, text: str, *, limit: int = 30) -> list[Card]:
    """Generate Anki cards from a passage. Returns up to `limit` cards.

    The LLM is asked to be exhaustive; `limit` is a cap, not a target.
    """
    text = text.strip()
    if len(text) < 100:
        return []
    user = (
        f"Extract ALL useful language items from this passage — be exhaustive. "
        f"Include vocabulary, phrasal verbs, collocations, idioms, and academic "
        f"phrases. Aiming for at least {limit} items.\n\n"
        f"PASSAGE:\n{text}"
    )
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

        # Build card back: definition + example + Russian translation.
        parts: list[str] = [fc.definition.strip()]
        if fc.example.strip():
            parts.append(f"\n<i>{fc.example.strip()}</i>")
        ru = getattr(fc, "translation_ru", "") or ""
        if ru.strip():
            parts.append(f"\n🇷🇺 {ru.strip()}")
        back = "\n".join(parts)

        kind = fc.kind.strip().lower()
        tag_map = {
            "phrasal_verb": "phrasal_verb",
            "collocation": "collocation",
            "idiom": "idiom",
            "phrase": "phrase",
        }
        tag = tag_map.get(kind, "vocab")
        cards.append(Card(front=term, back=back, tags=["toefl", tag]))
        if len(cards) >= limit:
            break
    return cards
