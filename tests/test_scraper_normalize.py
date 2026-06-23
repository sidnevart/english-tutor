"""Pure channel-message -> RawItem normalization and EPUB text extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.telegram_scraper import _epub_text, _epub_title, is_suitable, normalize


def _raw(body: str) -> RawItem:
    return RawItem(
        source_type=SourceType.CHANNEL,
        source_ref="1",
        external_id="x",
        content_type=ContentType.ARTICLE,
        body_text=body,
    )


def test_is_suitable_keeps_long_english():
    assert is_suitable(_raw("This is a sufficiently long English passage. " * 12)) is True


def test_is_suitable_drops_short_blurb():
    assert is_suitable(_raw("Brian Tracy - Eat That Frog!")) is False


def test_is_suitable_drops_cyrillic_ad():
    assert is_suitable(_raw("Летние цены на английский: скидки до 40% и подарки. " * 12)) is False


def test_is_suitable_drops_overly_long_article():
    # Exceeds default max_len=4500.
    long_body = "This is a perfectly normal English sentence for testing. " * 100
    assert is_suitable(_raw(long_body)) is False


def test_is_suitable_keeps_article_within_custom_max():
    body = "This is a perfectly normal English sentence for testing. " * 10
    assert is_suitable(_raw(body), max_len=10000) is True


@dataclass
class FakeMsg:
    id: int
    text: str | None = None
    caption: str | None = None
    date: datetime | None = None


def test_normalize_text_post():
    msg = FakeMsg(id=5, text="Headline here\nThe body continues.", date=datetime.now(UTC))
    raw = normalize(msg, -1001137165265)
    assert raw is not None
    assert raw.source_type == SourceType.CHANNEL
    assert raw.content_type == ContentType.ARTICLE
    assert raw.external_id == "5"
    assert raw.title == "Headline here"
    assert raw.url == "https://t.me/c/1137165265/5"
    assert raw.body_text.startswith("Headline here")


def test_normalize_falls_back_to_caption():
    raw = normalize(FakeMsg(id=2, caption="A photo caption"), 1137165265)
    assert raw is not None
    assert raw.body_text == "A photo caption"
    assert raw.url == "https://t.me/c/1137165265/2"


def test_normalize_skips_empty_message():
    assert normalize(FakeMsg(id=1), 1137165265) is None


# ---------------------------------------------------------------------------
# EPUB text helpers
# ---------------------------------------------------------------------------

_XHTML_CHAPTER = b"""<?xml version="1.0"?>
<html><body>
<h2>Chapter One: The Beginning</h2>
<p>It was the best of times, it was the worst of times. The long and winding
road leads to meaningful discovery and understanding of the human condition.</p>
<p>Another paragraph with more English text that makes this chapter long enough
to be considered a real article worth reading and studying carefully.</p>
</body></html>
"""


def test_epub_text_strips_html():
    text = _epub_text(_XHTML_CHAPTER)
    assert "<" not in text
    assert "Chapter One" in text
    assert "It was the best of times" in text


def test_epub_text_collapses_whitespace():
    text = _epub_text(_XHTML_CHAPTER)
    assert "\n" not in text
    assert "  " not in text


def test_epub_title_extracts_h2():
    title = _epub_title(_XHTML_CHAPTER, fallback="fallback")
    assert title == "Chapter One: The Beginning"


def test_epub_title_falls_back_when_no_heading():
    html = b"<html><body><p>Just a paragraph, no heading here.</p></body></html>"
    title = _epub_title(html, fallback="chapter01.xhtml")
    assert title == "chapter01.xhtml"
