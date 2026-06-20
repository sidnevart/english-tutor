"""Repository round-trips for quizzes, attempts, and vocabulary."""

from __future__ import annotations

from tutor.domain import ContentType, QuizKind, QuizQuestion, RawItem, SourceType, VocabItem


def test_cross_source_dedup_by_body(repo):
    def raw(source_ref: str, ext: str) -> RawItem:
        return RawItem(
            source_type=SourceType.CHANNEL,
            source_ref=source_ref,
            external_id=ext,
            content_type=ContentType.ARTICLE,
            body_text="The very same article body, cross-posted to two channels.",
        )

    first = repo.add_content(raw("111", "1"), user_id=764315256)
    second = repo.add_content(raw("222", "2"), user_id=764315256)  # different source, same body
    assert first is not None
    assert second is None


def test_quiz_roundtrip_and_attempts(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    questions = [
        QuizQuestion(
            prompt="What is the main idea?",
            options=["A", "B", "C", "D"],
            correct_index=2,
            explanation="C is correct.",
        ),
        QuizQuestion(
            prompt="What does the author imply?",
            options=["X", "Y"],
            correct_index=0,
        ),
    ]
    repo.save_quiz(cid, QuizKind.READING, questions)
    assert all(q.id is not None for q in questions)

    quiz = repo.get_quiz(cid, QuizKind.READING)
    assert quiz is not None
    assert len(quiz.questions) == 2
    assert quiz.questions[0].options == ["A", "B", "C", "D"]
    assert quiz.questions[0].correct_index == 2

    q0 = quiz.questions[0]
    repo.record_attempt(q0.id, user_id=764315256, chosen_index=2, is_correct=True)
    repo.record_attempt(quiz.questions[1].id, user_id=764315256, chosen_index=1, is_correct=False)

    attempts = repo.attempts_for_content(cid, user_id=764315256)
    assert len(attempts) == 2
    assert [a.is_correct for a in attempts] == [True, False]


def test_vocab_roundtrip_is_idempotent(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    items = [
        VocabItem(content_id=cid, word="ubiquitous", definition="found everywhere", freq_rank=3.1),
        VocabItem(content_id=cid, word="ephemeral", definition="short-lived", freq_rank=2.8),
    ]
    repo.save_vocab(cid, items)
    repo.save_vocab(cid, items)  # second write must not duplicate (UNIQUE)

    stored = repo.get_vocab(cid)
    assert {v.word for v in stored} == {"ubiquitous", "ephemeral"}
    # ordered by freq_rank ascending (rarer first)
    assert stored[0].word == "ephemeral"
