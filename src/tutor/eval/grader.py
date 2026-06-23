"""Local grading — pure key comparison, zero LLM.

Single-select questions store the chosen option as a plain index. Multi-select
("summary") questions store the chosen SET as a bitmask in the same integer
column, so the `attempt` table needs no schema change.
"""

from __future__ import annotations

from tutor.domain.models import QuizQuestion


def indices_to_mask(indices: list[int]) -> int:
    """Encode a set of option indices as a bitmask (option i -> bit i)."""
    mask = 0
    for i in indices:
        mask |= 1 << i
    return mask


def mask_to_indices(mask: int) -> list[int]:
    """Decode a bitmask back into a sorted list of option indices."""
    out: list[int] = []
    i = 0
    while mask:
        if mask & 1:
            out.append(i)
        mask >>= 1
        i += 1
    return out


def is_correct(question: QuizQuestion, chosen_index: int) -> bool:
    if question.is_multi:
        # `chosen_index` is a bitmask of the learner's selected options.
        return chosen_index == indices_to_mask(question.correct_indices)
    return chosen_index == question.correct_index


def score(questions: list[QuizQuestion], answers: dict[int, int]) -> tuple[int, int]:
    """Return (correct, total). `answers` maps question id -> chosen index."""
    correct = sum(1 for q in questions if q.id is not None and is_correct(q, answers.get(q.id, -1)))
    return correct, len(questions)
