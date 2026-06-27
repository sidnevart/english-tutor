"""Worksheet table repo methods and normalize_letter utility."""

from __future__ import annotations

from tutor.domain import VocabItem
from tutor.worksheet.parser import normalize_letter


def test_worksheet_repo_roundtrip(repo):
    """save_worksheet → get_worksheet → update_answers → update_grade."""
    items_json = '{"reading": [], "listening": []}'
    ws_id = repo.save_worksheet(764315256, items_json)
    assert ws_id > 0

    ws = repo.get_worksheet(ws_id)
    assert ws is not None
    assert ws["status"] == "pending"
    assert ws["items_json"] == items_json

    # Submit answers.
    repo.update_worksheet_answers(ws_id, "**Your answer:** A")
    ws = repo.get_worksheet(ws_id)
    assert ws["status"] == "submitted"
    assert ws["answers"] == "**Your answer:** A"

    # Grade.
    repo.update_worksheet_grade(ws_id, 0.85, "Good work!")
    ws = repo.get_worksheet(ws_id)
    assert ws["status"] == "graded"
    assert ws["score"] == 0.85
    assert ws["feedback"] == "Good work!"


def test_get_latest_worksheet(repo):
    """Should return the most recent worksheet with given status."""
    items_json = "{}"
    repo.save_worksheet(764315256, items_json)
    repo.save_worksheet(764315256, items_json)

    ws = repo.get_latest_worksheet(764315256, status="pending")
    assert ws is not None

    # No graded worksheets yet.
    ws = repo.get_latest_worksheet(764315256, status="graded")
    assert ws is None


def test_get_vocab_today(repo, sample_raw):
    """Should return vocab from items delivered today."""
    cid = repo.add_content(sample_raw(), user_id=764315256)
    repo.mark_delivered(cid)
    repo.save_vocab(
        cid,
        [VocabItem(content_id=cid, word="test", definition="def", freq_rank=3.0)],
    )
    vocab = repo.get_vocab_today(764315256)
    assert len(vocab) >= 1
    assert any(v.word == "test" for v in vocab)


def test_get_today_articles(repo, sample_raw):
    """Should return articles delivered today."""
    cid = repo.add_content(sample_raw(), user_id=764315256)
    repo.mark_delivered(cid)
    articles = repo.get_today_articles(764315256)
    assert len(articles) >= 1


def test_normalize_letter():
    assert normalize_letter("A") == 0
    assert normalize_letter("d") == 3
    assert normalize_letter("X") is None
    assert normalize_letter("1") == 1
    assert normalize_letter("") is None
