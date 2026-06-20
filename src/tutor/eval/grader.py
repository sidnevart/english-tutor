"""Local grading — pure key comparison, zero LLM."""

from __future__ import annotations

from tutor.domain.models import QuizQuestion


def is_correct(question: QuizQuestion, chosen_index: int) -> bool:
    return chosen_index == question.correct_index


def score(questions: list[QuizQuestion], answers: dict[int, int]) -> tuple[int, int]:
    """Return (correct, total). `answers` maps question id -> chosen index."""
    correct = sum(1 for q in questions if q.id is not None and is_correct(q, answers.get(q.id, -1)))
    return correct, len(questions)
