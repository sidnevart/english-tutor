"""Unit tests for article RSS ingestion (pure helpers — no network)."""

from __future__ import annotations

from tutor.ingest.article_rss import _strip_html, _truncate, normalize_entry


def test_strip_html_removes_tags_and_collapses_whitespace() -> None:
    assert _strip_html("<p>Hello <b>world</b>!</p>") == "Hello world!"


def test_truncate_short_text_unchanged() -> None:
    assert _truncate("short text", 100) == "short text"


def test_truncate_long_text_ends_on_sentence() -> None:
    text = "Sentence one. " * 500  # very long
    out = _truncate(text, 200)
    assert len(out) <= 200
    assert out.endswith(".")


def test_truncate_long_text_without_sentence_ends_on_word() -> None:
    text = "word " * 500
    out = _truncate(text, 200)
    assert len(out) <= 200
    assert not out.endswith(" ")


def test_normalize_entry_prefers_full_content_over_summary() -> None:
    entry = {
        "title": "Climate breakthrough",
        "content": [{"value": "<p>A long detailed body " + "x" * 500 + "</p>"}],
        "summary": "short summary",
        "link": "https://example.com/a",
        "id": "guid-1",
    }
    raw = normalize_entry(entry, "The Conversation", min_chars=50, max_chars=400)
    assert raw is not None
    assert raw.title == "Climate breakthrough"
    assert raw.source_ref == "The Conversation"
    assert "short summary" not in raw.body_text  # used full content, not summary
    assert len(raw.body_text) <= 400
    assert raw.external_id == "guid-1"


def test_normalize_entry_drops_short_blurbs() -> None:
    entry = {"title": "Ad", "summary": "buy now", "link": "https://x", "id": "x"}
    assert normalize_entry(entry, "NPR", min_chars=50, max_chars=400) is None


def test_normalize_entry_falls_back_to_summary() -> None:
    entry = {"title": "T", "summary": "S" * 200, "link": "https://x", "id": "i"}
    raw = normalize_entry(entry, "AEON", min_chars=50, max_chars=400)
    assert raw is not None
    assert raw.body_text.startswith("S")
