"""Quiz generation against the stub LLM, plus local grading."""

from __future__ import annotations

from datetime import UTC, datetime

from tutor.adapters.llm.stub import StubLLMClient
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import ContentItem, QuizQuestion
from tutor.eval.grader import is_correct, score
from tutor.eval.quiz_builder import build_reading_quiz


def _content() -> ContentItem:
    return ContentItem(
        id=1,
        user_id=1,
        source_type=SourceType.CHANNEL,
        source_ref="1137165265",
        external_id="x",
        content_type=ContentType.ARTICLE,
        body_text="A passage about science and discovery.",
        fetched_at=datetime.now(UTC),
    )


async def test_build_reading_quiz_is_well_formed():
    quiz = await build_reading_quiz(StubLLMClient(), _content(), n=3)
    assert len(quiz) == 3
    for q in quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < len(q.options)


def test_grader_scores_local_key_compare():
    questions = [
        QuizQuestion(id=1, prompt="q1", options=["a", "b"], correct_index=1),
        QuizQuestion(id=2, prompt="q2", options=["a", "b"], correct_index=0),
    ]
    assert is_correct(questions[0], 1) is True
    assert is_correct(questions[0], 0) is False

    correct, total = score(questions, {1: 1, 2: 1})  # q2 wrong
    assert (correct, total) == (1, 2)
