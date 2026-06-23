"""Quiz generation against the stub LLM, plus local grading."""

from __future__ import annotations

from datetime import UTC, datetime

from tutor.adapters.llm.stub import StubLLMClient
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import ContentItem, QuizQuestion
from tutor.eval.grader import is_correct, score
from tutor.eval.quiz_builder import build_listening_quiz, build_reading_quiz


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


def _podcast_content() -> ContentItem:
    return ContentItem(
        id=2,
        user_id=1,
        source_type=SourceType.RSS,
        source_ref="Short Wave",
        external_id="p1",
        content_type=ContentType.PODCAST,
        body_text=(
            "Today we explore the fascinating world of quantum computing "
            "and its implications for society."
        ),
        audio_url="https://cdn/ep1.mp3",
        duration_sec=600,
        fetched_at=datetime.now(UTC),
    )


async def test_build_reading_quiz_is_well_formed():
    quiz = await build_reading_quiz(StubLLMClient(), _content(), n=3)
    assert len(quiz) == 3
    for q in quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < len(q.options)


async def test_build_reading_quiz_custom_n():
    quiz = await build_reading_quiz(StubLLMClient(), _content(), n=5)
    # Stub always returns 3, but the function should handle any n gracefully.
    assert len(quiz) >= 1
    for q in quiz:
        assert len(q.options) >= 2
        assert 0 <= q.correct_index < len(q.options)


async def test_build_reading_quiz_with_recall_hint():
    quiz = await build_reading_quiz(
        StubLLMClient(), _content(), n=3, recall_hint="The learner struggles with inference."
    )
    assert len(quiz) == 3


async def test_build_listening_quiz_is_well_formed():
    quiz = await build_listening_quiz(StubLLMClient(), _podcast_content(), n=3)
    assert len(quiz) == 3
    for q in quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < len(q.options)


async def test_build_listening_quiz_rejects_out_of_range_correct_index():
    from unittest.mock import AsyncMock

    from tutor.eval.schemas import QuestionPayload, ReadingQuizPayload

    bad_payload = ReadingQuizPayload(
        questions=[
            QuestionPayload(
                prompt="Good listening question",
                options=["A", "B", "C", "D"],
                correct_index=2,
                explanation="",
            ),
            QuestionPayload(
                prompt="Bad question",
                options=["A", "B"],
                correct_index=5,
                explanation="",
            ),
        ]
    )
    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(return_value=bad_payload)

    quiz = await build_listening_quiz(mock_llm, _podcast_content(), n=3)
    assert len(quiz) == 1
    assert quiz[0].prompt == "Good listening question"


async def test_build_reading_quiz_rejects_out_of_range_correct_index():
    """If the LLM returns correct_index >= len(options), that question is dropped."""
    from unittest.mock import AsyncMock

    from tutor.eval.schemas import QuestionPayload, ReadingQuizPayload

    # Simulate a malformed response: one question has correct_index=10.
    bad_payload = ReadingQuizPayload(
        questions=[
            QuestionPayload(
                prompt="Good question",
                options=["A", "B", "C", "D"],
                correct_index=1,
                explanation="",
            ),
            QuestionPayload(
                prompt="Bad question",
                options=["A", "B"],
                correct_index=10,  # out of range
                explanation="",
            ),
        ]
    )
    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(return_value=bad_payload)

    quiz = await build_reading_quiz(mock_llm, _content(), n=3)
    # Only the well-formed question should survive.
    assert len(quiz) == 1
    assert quiz[0].prompt == "Good question"


def test_grader_scores_local_key_compare():
    questions = [
        QuizQuestion(id=1, prompt="q1", options=["a", "b"], correct_index=1),
        QuizQuestion(id=2, prompt="q2", options=["a", "b"], correct_index=0),
    ]
    assert is_correct(questions[0], 1) is True
    assert is_correct(questions[0], 0) is False

    correct, total = score(questions, {1: 1, 2: 1})  # q2 wrong
    assert (correct, total) == (1, 2)


def test_mask_roundtrip():
    from tutor.eval.grader import indices_to_mask, mask_to_indices

    assert indices_to_mask([0, 2, 4]) == 0b10101
    assert mask_to_indices(0b10101) == [0, 2, 4]
    assert mask_to_indices(indices_to_mask([1, 3])) == [1, 3]


def test_grader_multiselect_summary():
    from tutor.eval.grader import indices_to_mask

    q = QuizQuestion(
        id=9,
        prompt="Pick the 3 best summary statements.",
        options=["a", "b", "c", "d", "e", "f"],
        correct_index=0,
        correct_indices=[0, 2, 4],
    )
    assert q.is_multi
    # Exact set matches.
    assert is_correct(q, indices_to_mask([0, 2, 4])) is True
    # Wrong set (one swapped) fails.
    assert is_correct(q, indices_to_mask([0, 2, 5])) is False
    # Subset fails (must match the whole set).
    assert is_correct(q, indices_to_mask([0, 2])) is False


async def test_summary_question_conversion_and_persistence():
    """A multi-select payload becomes a gradeable multi question and round-trips."""
    from unittest.mock import AsyncMock

    from tutor.eval.schemas import QuestionPayload, ReadingQuizPayload

    payload = ReadingQuizPayload(
        questions=[
            QuestionPayload(
                prompt="Summary — choose 3",
                options=["a", "b", "c", "d", "e", "f"],
                correct_index=0,
                correct_indices=[0, 2, 4],
                question_type="summary",
            ),
            QuestionPayload(
                prompt="Multi with one out-of-range index gets filtered",
                options=["a", "b", "c", "d"],
                correct_index=0,
                correct_indices=[1, 9],  # 9 dropped -> only [1] -> too few -> question dropped
            ),
        ]
    )
    mock_llm = AsyncMock()
    mock_llm.complete_json = AsyncMock(return_value=payload)

    quiz = await build_reading_quiz(mock_llm, _content(), n=10)
    assert len(quiz) == 1
    q = quiz[0]
    assert q.is_multi
    assert q.correct_indices == [0, 2, 4]
