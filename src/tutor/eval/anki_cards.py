"""Build Anki cards from the day's vocabulary and the questions missed."""

from __future__ import annotations

from tutor.domain.models import Card, ContentItem, QuizQuestion, VocabItem


def build_cards(
    content: ContentItem,
    vocab: list[VocabItem],
    missed: list[QuizQuestion],
) -> list[Card]:
    cards: list[Card] = []
    src = content.title or content.url or f"item {content.id}"

    for v in vocab:
        back = v.definition or "(define this word in context)"
        if v.example:
            back += f"\n\n{v.example}"
        cards.append(Card(front=v.word, back=back, tags=["toefl", "vocab"]))

    for q in missed:
        correct = q.options[q.correct_index]
        back = correct if not q.explanation else f"{correct}\n\n{q.explanation}"
        cards.append(Card(front=q.prompt, back=back, tags=["toefl", "reading"]))

    # Attribution footer keeps cards traceable to their source content.
    for c in cards:
        c.back = f"{c.back}\n\n— {src}"
    return cards
