"""Message rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import ContentItem, QuizQuestion
from tutor.render import render_card, render_question, render_score


def _item(content_type: ContentType, **kw) -> ContentItem:
    base = dict(
        id=1,
        user_id=1,
        source_type=SourceType.RSS if content_type == ContentType.PODCAST else SourceType.CHANNEL,
        source_ref="Short Wave",
        external_id="x",
        content_type=content_type,
        fetched_at=datetime.now(UTC),
    )
    base.update(kw)
    return ContentItem(**base)


def test_render_card_podcast_uses_headphones_and_duration():
    card = render_card(_item(ContentType.PODCAST, title="Robots on the Moon", duration_sec=660))
    assert card.startswith("🎧")
    assert "11 min" in card
    assert "Short Wave" in card


def test_render_card_article_uses_newspaper():
    card = render_card(_item(ContentType.ARTICLE, title="A Reading", body_text="Some body text."))
    assert card.startswith("📰")


def test_render_question_lists_lettered_options_in_body():
    q = QuizQuestion(
        prompt="What is the main idea?", options=["aa", "bb", "cc", "dd"], correct_index=1
    )
    text = render_question(0, 3, q)
    assert text.startswith("<b>Question 1/3</b>")
    assert "What is the main idea?" in text
    assert "<b>A.</b> aa" in text
    assert "<b>D.</b> dd" in text


def test_render_score_buckets():
    assert "2/3" in render_score(2, 3)
    assert render_score(0, 0).endswith("(0%).")
