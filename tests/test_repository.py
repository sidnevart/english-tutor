"""Repository round-trips for quizzes, attempts, and vocabulary."""

from __future__ import annotations

from tutor.domain import QuizKind, QuizQuestion, VocabItem


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
