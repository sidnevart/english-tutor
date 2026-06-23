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


# Chunking for long passages/transcripts: each chunk is extracted independently
# (in parallel) and the results are merged + deduplicated. This makes extraction
# genuinely exhaustive for long content instead of relying on one bounded call.
_CHUNK_SIZE = 3000
_MAX_CHUNKS = 24  # safety cap on parallel LLM calls (~72k chars of content)


def _chunks(text: str) -> list[str]:
    if len(text) <= _CHUNK_SIZE:
        return [text]
    return [text[i : i + _CHUNK_SIZE] for i in range(0, len(text), _CHUNK_SIZE)][:_MAX_CHUNKS]


def _card_from(fc: object, full_text: str) -> Card | None:
    """Build a Card from one extracted item, verifying it occurs in the source."""
    term = fc.term.strip()  # type: ignore[attr-defined]
    if not term or not _present(term, full_text):
        return None
    parts: list[str] = [fc.definition.strip()]  # type: ignore[attr-defined]
    if fc.example.strip():  # type: ignore[attr-defined]
        parts.append(f"\n<i>{fc.example.strip()}</i>")  # type: ignore[attr-defined]
    ru = getattr(fc, "translation_ru", "") or ""
    if ru.strip():
        parts.append(f"\n🇷🇺 {ru.strip()}")
    back = "\n".join(parts)
    tag_map = {
        "phrasal_verb": "phrasal_verb",
        "collocation": "collocation",
        "idiom": "idiom",
        "phrase": "phrase",
    }
    tag = tag_map.get(fc.kind.strip().lower(), "vocab")  # type: ignore[attr-defined]
    return Card(front=term, back=back, tags=["toefl", tag])


async def make_flashcards(
    llm: LLMClient,
    text: str,
    *,
    limit: int | None = None,
    exclude: set[str] | None = None,
) -> list[Card]:
    """Generate Anki cards from a passage. `limit=None` means unlimited.

    Long texts are split into chunks and extracted in parallel, then merged and
    deduplicated by term. `exclude` is a set of lowercased terms already known to
    the learner (e.g. previously generated cards) that should be skipped.
    """
    import asyncio

    text = text.strip()
    if len(text) < 100:
        return []

    chunks = _chunks(text)
    user_tmpl = (
        "Extract ALL useful language items from this passage — be exhaustive, no cap. "
        "Include vocabulary, phrasal verbs, collocations, idioms, and academic phrases. "
        "Do not stop early.\n\n"
        "PASSAGE:\n{chunk}"
    )

    async def _one(chunk: str) -> FlashcardPayload | None:
        try:
            return await llm.complete_json(_SYSTEM, user_tmpl.format(chunk=chunk), FlashcardPayload)
        except Exception:  # noqa: BLE001 — cards are best-effort, never block delivery
            return None

    payloads = await asyncio.gather(*[_one(c) for c in chunks])

    cards: list[Card] = []
    seen: set[str] = set(exclude or set())
    for payload in payloads:
        if payload is None:
            continue
        for fc in payload.cards:
            key = fc.term.strip().lower()
            if not key or key in seen:
                continue
            card = _card_from(fc, text)
            if card is None:
                continue
            seen.add(key)
            cards.append(card)
            if limit is not None and len(cards) >= limit:
                return cards
    return cards
