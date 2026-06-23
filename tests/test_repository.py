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


def test_fetch_by_status_filters_by_content_type(repo):
    from tutor.domain.enums import DeliveryStatus

    repo.add_content(
        RawItem(
            source_type=SourceType.CHANNEL,
            source_ref="c",
            external_id="a1",
            content_type=ContentType.ARTICLE,
            body_text="An article body about science.",
        ),
        user_id=764315256,
    )
    repo.add_content(
        RawItem(
            source_type=SourceType.RSS,
            source_ref="Short Wave",
            external_id="p1",
            content_type=ContentType.PODCAST,
            audio_url="https://cdn/x.mp3",
        ),
        user_id=764315256,
    )

    podcasts = repo.fetch_by_status(764315256, DeliveryStatus.NEW, content_type=ContentType.PODCAST)
    assert [c.content_type for c in podcasts] == [ContentType.PODCAST]
    articles = repo.fetch_by_status(764315256, DeliveryStatus.NEW, content_type=ContentType.ARTICLE)
    assert [c.content_type for c in articles] == [ContentType.ARTICLE]


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


def test_reset_progress_clears_all_and_resets_status(repo, sample_raw):
    """reset_progress deletes attempts, cards, quizzes, essays, errors, and
    resets content_item status to NEW."""
    from tutor.domain.enums import DeliveryStatus
    from tutor.domain.models import Card

    uid = 764315256

    # Add content and progress.
    cid = repo.add_content(sample_raw(), user_id=uid)
    repo.mark_delivered(cid)

    questions = [
        QuizQuestion(prompt="Q1", options=["A", "B"], correct_index=0, explanation=""),
    ]
    repo.save_quiz(cid, QuizKind.READING, questions)
    quiz = repo.get_quiz(cid, QuizKind.READING)
    repo.record_attempt(quiz.questions[0].id, uid, chosen_index=0, is_correct=True)

    repo.save_vocab(cid, [VocabItem(content_id=cid, word="test", definition="def", freq_rank=3.0)])
    repo.save_anki_cards(cid, [Card(front="f", back="b")], deck="test", sink="genanki")
    repo.save_session_errors(uid, "speak", [{"type": "grammar", "error": "e", "correction": "c"}])
    repo.record_topic_progress(uid, "science", "quiz", cid, 0.8)
    repo.save_essay(uid, "prompt", "text", 4, "ok", "independent")

    # Verify data exists.
    assert repo.count_status(uid, DeliveryStatus.DELIVERED) == 1
    assert len(repo.attempts_for_content(cid, uid)) == 1
    assert repo.anki_card_count(uid) == 1
    assert repo.essay_count(uid) == 1

    # Reset.
    counts = repo.reset_progress(uid)
    assert counts["attempts"] == 1
    assert counts["anki_cards"] == 1
    assert counts["quizzes"] == 1
    assert counts["essays"] == 1
    assert counts["session_errors"] == 1
    assert counts["topic_progress"] == 1

    # Content is back to NEW.
    assert repo.count_status(uid, DeliveryStatus.NEW) == 1
    assert repo.count_status(uid, DeliveryStatus.DELIVERED) == 0
    assert repo.count_status(uid, DeliveryStatus.REVIEWED) == 0

    # Quiz, attempts, cards, essays are gone.
    assert repo.get_quiz(cid, QuizKind.READING) is None
    assert repo.attempts_for_content(cid, uid) == []
    assert repo.anki_card_count(uid) == 0
    assert repo.essay_count(uid) == 0


def test_get_quiz_auto_returns_reading_for_article(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    questions = [
        QuizQuestion(prompt="Q1", options=["A", "B"], correct_index=0, explanation=""),
    ]
    repo.save_quiz(cid, QuizKind.READING, questions)
    quiz = repo.get_quiz_auto(cid)
    assert quiz is not None
    assert quiz.kind == QuizKind.READING


def test_channel_watermark_roundtrip(repo):
    repo.set_watermark("1234567", max_id=1000, min_id=800)
    wm = repo.get_watermark("1234567")
    assert wm is not None
    assert wm["max_scraped_id"] == 1000
    assert wm["min_scraped_id"] == 800


def test_channel_watermark_extends_range(repo):
    repo.set_watermark("ch", max_id=500, min_id=400)
    repo.set_watermark("ch", max_id=600, min_id=200)  # wider range
    wm = repo.get_watermark("ch")
    assert wm["max_scraped_id"] == 600  # always grows
    assert wm["min_scraped_id"] == 200  # always shrinks


def test_channel_watermark_never_shrinks(repo):
    repo.set_watermark("ch2", max_id=1000, min_id=100)
    repo.set_watermark("ch2", max_id=900, min_id=500)  # narrower range (stale run)
    wm = repo.get_watermark("ch2")
    assert wm["max_scraped_id"] == 1000  # kept the higher max
    assert wm["min_scraped_id"] == 100  # kept the lower min


def test_channel_watermark_returns_none_before_first_run(repo):
    assert repo.get_watermark("never_seen") is None


def test_get_quiz_auto_returns_listening_for_podcast(repo):
    raw = RawItem(
        source_type=SourceType.RSS,
        source_ref="Short Wave",
        external_id="p1",
        content_type=ContentType.PODCAST,
        audio_url="https://cdn/x.mp3",
        body_text="A podcast transcript about science and ideas.",
    )
    cid = repo.add_content(raw, user_id=764315256)
    questions = [
        QuizQuestion(prompt="Q1", options=["A", "B"], correct_index=0, explanation=""),
    ]
    repo.save_quiz(cid, QuizKind.LISTENING, questions)
    quiz = repo.get_quiz_auto(cid)
    assert quiz is not None
    assert quiz.kind == QuizKind.LISTENING
