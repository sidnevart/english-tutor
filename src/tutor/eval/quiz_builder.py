"""Reading-comprehension quiz generation — the one LLM call on the graded path.

`complete_json` returns a validated `ReadingQuizPayload`; we then drop any
question whose `correct_index` is out of range, so a malformed model response
can never produce an ungradeable quiz.
"""

from __future__ import annotations

from tutor.domain.models import ContentItem, QuizQuestion
from tutor.eval.schemas import ReadingQuizPayload
from tutor.interfaces.llm import LLMClient

_SYSTEM = (
    "You are a TOEFL reading-comprehension coach. You write rigorous "
    "multiple-choice questions that test main idea, inference, vocabulary in "
    "context, and detail. Exactly one option is correct."
)


def _user_prompt(passage: str, n: int, recall_hint: str = "") -> str:
    base = (
        f"Write {n} TOEFL reading-comprehension multiple-choice questions about "
        f"the passage below. Each question must have exactly 4 options, one "
        f"correct, and a short explanation.\n\nPASSAGE:\n{passage}"
    )
    return f"{base}\n\n{recall_hint}" if recall_hint else base


async def build_reading_quiz(
    llm: LLMClient,
    content: ContentItem,
    n: int = 3,
    *,
    system: str | None = None,
    recall_hint: str = "",
) -> list[QuizQuestion]:
    payload = await llm.complete_json(
        system or _SYSTEM, _user_prompt(content.body_text, n, recall_hint), ReadingQuizPayload
    )
    questions: list[QuizQuestion] = []
    for q in payload.questions:
        if 0 <= q.correct_index < len(q.options):
            questions.append(
                QuizQuestion(
                    prompt=q.prompt,
                    options=q.options,
                    correct_index=q.correct_index,
                    explanation=q.explanation,
                )
            )
    return questions
