"""The learning loop: deliver -> build evaluation -> grade & export.

Pure orchestration over Services. Works identically on stub or real adapters,
which is what makes the whole loop runnable offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tutor.domain.enums import DeliveryStatus, QuizKind
from tutor.domain.models import AnkiResult, Quiz
from tutor.eval.anki_cards import build_cards
from tutor.eval.grader import is_correct
from tutor.eval.quiz_builder import build_reading_quiz
from tutor.eval.vocab import select_vocab
from tutor.factory import Services
from tutor.render import render_card, render_score


@dataclass
class ReviewResult:
    content_id: int
    correct: int
    total: int
    anki: AnkiResult


async def deliver_new(svc: Services, user_id: int, limit: int = 5) -> list[int]:
    """Push NEW items to the learner and mark them DELIVERED."""
    delivered: list[int] = []
    for item in svc.repo.fetch_by_status(user_id, DeliveryStatus.NEW, limit):
        keyboard = [[("📖 Quiz me", f"quiz:{item.id}")]]
        await svc.notifier.send(user_id, render_card(item), keyboard=keyboard)
        svc.repo.mark_delivered(item.id)
        delivered.append(item.id)
    return delivered


async def build_evaluation(
    svc: Services, content_id: int, *, vocab_limit: int = 8, n_questions: int = 3
) -> Quiz:
    """Select vocabulary (deterministic) and generate a reading quiz (LLM)."""
    content = svc.repo.get(content_id)
    if content is None:
        raise KeyError(f"content_item {content_id} not found")

    svc.repo.save_vocab(content_id, select_vocab(content_id, content.body_text, limit=vocab_limit))
    questions = await build_reading_quiz(svc.llm, content, n=n_questions)
    svc.repo.save_quiz(content_id, QuizKind.READING, questions)

    quiz = svc.repo.get_quiz(content_id, QuizKind.READING)
    assert quiz is not None
    return quiz


async def finalize_review(svc: Services, content_id: int, user_id: int) -> ReviewResult:
    """Grade from recorded attempts, export Anki cards, mark REVIEWED.

    Derives the missed questions from the `attempt` table (the source of truth),
    so it works whether answers were recorded one-by-one (interactive bot) or in
    a batch. Idempotent: if already REVIEWED it does not re-transition.
    """
    quiz = svc.repo.get_quiz(content_id, QuizKind.READING)
    if quiz is None:
        raise KeyError(f"no quiz for content_item {content_id}")

    attempts = {a.quiz_question_id: a for a in svc.repo.attempts_for_content(content_id, user_id)}
    missed = [q for q in quiz.questions if not (attempts.get(q.id) and attempts[q.id].is_correct)]
    correct = len(quiz.questions) - len(missed)

    content = svc.repo.get(content_id)
    assert content is not None
    cards = build_cards(content, svc.repo.get_vocab(content_id), missed)
    anki = await svc.anki.add_cards(svc.settings.anki_deck, cards)
    svc.repo.save_anki_cards(content_id, cards, svc.settings.anki_deck, anki.sink)

    if content.status != DeliveryStatus.REVIEWED:
        svc.repo.mark_reviewed(content_id)

    return ReviewResult(content_id, correct, len(quiz.questions), anki)


async def submit_answers(
    svc: Services, content_id: int, user_id: int, answers: dict[int, int]
) -> ReviewResult:
    """Record a batch of answers, then finalize. (The bot records incrementally
    and calls finalize_review directly.)"""
    quiz = svc.repo.get_quiz(content_id, QuizKind.READING)
    if quiz is None:
        raise KeyError(f"no quiz for content_item {content_id}")

    for q in quiz.questions:
        chosen = answers.get(q.id, -1)
        svc.repo.record_attempt(q.id, user_id, chosen, is_correct(q, chosen))

    result = await finalize_review(svc, content_id, user_id)
    await svc.notifier.send(user_id, render_score(result.correct, result.total))
    if result.anki.apkg_path:
        await svc.notifier.send_file(
            user_id, Path(result.anki.apkg_path), caption="🎴 Your Anki cards for today"
        )
    return result
