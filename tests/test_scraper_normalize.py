"""Pure channel-message -> RawItem normalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.telegram_scraper import is_suitable, normalize


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
