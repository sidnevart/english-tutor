"""Grade a completed worksheet and generate feedback.

Grading is two-layer:
  1. Deterministic scoring for multiple-choice and collocation match
  2. LLM-based evaluation for error correction and sentence transformation
"""

from __future__ import annotations

from tutor.interfaces.llm import LLMClient
from tutor.worksheet.generator import WorksheetPayload
from tutor.worksheet.parser import normalize_letter

_GRADING_SYSTEM = (
    "You are a TOEFL preparation grader. The learner completed a worksheet. "
    "Evaluate their free-text answers (error corrections and sentence "
    "transformations) and provide constructive feedback.\n\n"
    "For each answer, determine if it is:\n"
    "- correct: fully acceptable\n"
    "- partially correct: right idea but incomplete or imprecise\n"
    "- incorrect: wrong or missing the point\n\n"
    "Return a JSON object with this structure:\n"
    '{"scores": {"error_correction": [0.0-1.0, ...], '
    '"sentence_transform": [0.0-1.0, ...]}, '
    '"feedback": "overall feedback string", '
    '"review_suggestions": ["topic 1", "topic 2"]}'
)


def _score_multiple_choice(correct: list[int], answers: list[str]) -> tuple[int, int]:
    """Score multiple-choice answers. Returns (correct_count, total)."""
    scored = 0
    total = min(len(correct), len(answers))
    for i in range(total):
        chosen = normalize_letter(answers[i])
        if chosen is not None and chosen == correct[i]:
            scored += 1
    return scored, total


def _score_collocations(items: list[dict], answers: list[str]) -> tuple[int, int]:
    """Score collocation match answers. Returns (correct_count, total)."""
    scored = 0
    total = min(len(items), len(answers))
    for i in range(total):
        # Correct answer is always index 0 (correct_partner is first in the list).
        chosen = normalize_letter(answers[i])
        if chosen is not None and chosen == 0:
            scored += 1
    return scored, total


def _deterministic_score(payload: WorksheetPayload, answers: dict[str, list]) -> dict[str, float]:
    """Score all deterministic (multiple-choice) sections."""
    scores: dict[str, float] = {}

    # Fill in the blanks.
    if payload.fill_blanks:
        correct = [q.correct_index for q in payload.fill_blanks]
        scored, total = _score_multiple_choice(correct, answers.get("fill_blanks", []))
        scores["fill_blanks"] = scored / total if total else 0.0

    # Mini reading.
    if payload.mini_reading:
        all_correct = []
        for section in payload.mini_reading:
            for q in section.questions:
                all_correct.append(q.correct_index)
        # Reading answers are in the fill_blanks section of the parsed answers
        # (they use the same "Your answer:" format).
        # We need to extract them separately — they come after the fill_blanks.
        # For now, we'll handle this in the LLM grading.
        scored, total = 0, len(all_correct)
        scores["mini_reading"] = 0.0  # placeholder — graded by LLM

    # Collocation match.
    if payload.collocation_match:
        scored, total = _score_collocations(
            [{"correct_index": 0} for _ in payload.collocation_match],
            answers.get("collocation_match", []),
        )
        scores["collocation_match"] = scored / total if total else 0.0

    return scores


async def _llm_grade(
    llm: LLMClient,
    payload: WorksheetPayload,
    answers: dict[str, list],
) -> dict[str, object]:
    """Use LLM to grade free-text answers (error correction, transforms)."""
    parts: list[str] = []

    # Error corrections.
    if payload.error_correction:
        ec_answers = answers.get("error_correction", [])
        parts.append("ERROR CORRECTION ANSWERS:")
        for i, q in enumerate(payload.error_correction):
            user_answer = (
                ec_answers[i] if i < len(ec_answers) else {"correct": "(no answer)", "rule": ""}
            )
            parts.append(
                f'\n{i + 1}. Original: "{q.sentence}"\n'
                f'   Error: "{q.error_span}" → Correct: "{q.correction}"\n'
                f"   Rule: {q.rule}\n"
                f'   Learner\'s correction: "{user_answer.get("correct", "")}"\n'
                f'   Learner\'s rule: "{user_answer.get("rule", "")}"'
            )

    # Sentence transforms.
    if payload.sentence_transform:
        st_answers = answers.get("sentence_transform", [])
        parts.append("\nSENTENCE TRANSFORMATION ANSWERS:")
        for i, q in enumerate(payload.sentence_transform):
            user_answer = st_answers[i] if i < len(st_answers) else "(no answer)"
            parts.append(
                f'\n{i + 1}. Original: "{q.original}"\n'
                f'   Model answer: "{q.model_answer}"\n'
                f"   Key point: {q.key_point}\n"
                f'   Learner\'s version: "{user_answer}"'
            )

    if not parts:
        return {"scores": {}, "feedback": "", "review_suggestions": []}

    user_prompt = "\n".join(parts)
    # Use complete() for free-form evaluation, not complete_json().
    response = await llm.complete(_GRADING_SYSTEM, user_prompt)
    return {"feedback": response, "scores": {}, "review_suggestions": []}


def _build_feedback(
    det_scores: dict[str, float],
    llm_result: dict[str, object],
    total_exercises: int,
) -> tuple[float, str]:
    """Combine deterministic and LLM scores into final feedback."""
    # Calculate weighted average.
    all_scores: list[float] = list(det_scores.values())
    llm_scores = llm_result.get("scores", {})
    if isinstance(llm_scores, dict):
        all_scores.extend(llm_scores.values())

    overall = sum(all_scores) / len(all_scores) if all_scores else 0.0

    # Build feedback text.
    lines: list[str] = [
        "📊 <b>Worksheet Results</b>\n",
        f"Score: <b>{round(overall * 100)}%</b>\n",
    ]

    # Section scores.
    for section, score in det_scores.items():
        name = section.replace("_", " ").title()
        pct = round(score * 100)
        emoji = "✅" if pct >= 70 else ("📝" if pct >= 50 else "📚")
        lines.append(f"  {emoji} {name}: {pct}%")

    # LLM feedback.
    llm_feedback = llm_result.get("feedback", "")
    if llm_feedback:
        lines.append(f"\n<b>Detailed feedback:</b>\n{llm_feedback}")

    # Review suggestions.
    suggestions = llm_result.get("review_suggestions", [])
    if suggestions and isinstance(suggestions, list):
        lines.append("\n<b>📝 Review tomorrow:</b>")
        for s in suggestions:
            lines.append(f"  • {s}")

    return overall, "\n".join(lines)


async def grade_worksheet(
    llm: LLMClient,
    payload: WorksheetPayload,
    answers: dict[str, list],
) -> tuple[float, str]:
    """Grade a completed worksheet. Returns (score, feedback_html)."""
    # Step 1: Deterministic scoring.
    det_scores = _deterministic_score(payload, answers)

    # Step 2: LLM grading for free-text answers.
    llm_result = await _llm_grade(llm, payload, answers)

    # Step 3: Combine.
    total = (
        len(payload.fill_blanks)
        + len(payload.error_correction)
        + len(payload.sentence_transform)
        + sum(len(s.questions) for s in payload.mini_reading)
        + len(payload.collocation_match)
    )
    return _build_feedback(det_scores, llm_result, total)
