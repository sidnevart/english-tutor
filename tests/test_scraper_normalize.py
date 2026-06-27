"""Pure channel-message -> RawItem normalization and announcement pairing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.telegram_scraper import (
    _announcement_ids,
    is_suitable,
    normalize,
)


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
# Announcement ↔ file pairing (file attachments are skipped, their blurb too)
# ---------------------------------------------------------------------------


@dataclass
class _Doc:
    mime_type: str = "application/pdf"
    size: int = 1_000_000


@dataclass
class _Media:
    document: _Doc | None = None


@dataclass
class FileMsg:
    """A message carrying a file attachment (no standalone article text)."""

    id: int
    media: _Media = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.media is None:
            self.media = _Media(document=_Doc())


def test_announcement_before_file_is_dropped():
    # Book channel pattern: text blurb (9621) then file (9622).
    by_id = {
        9621: FakeMsg(id=9621, text="The Memory Activity Book\nA short blurb."),
        9622: FileMsg(id=9622),
    }
    consumed = _announcement_ids(by_id)
    assert 9621 in consumed  # the blurb is paired with the file and skipped


def test_announcement_after_file_is_dropped():
    by_id = {
        100: FileMsg(id=100),
        101: FakeMsg(id=101, text="Description posted after the file."),
    }
    assert 101 in _announcement_ids(by_id)


def test_standalone_text_is_not_consumed():
    # A text post with no adjacent file stays a candidate article.
    by_id = {
        50: FakeMsg(id=50, text="A genuine standalone article with real content."),
    }
    assert _announcement_ids(by_id) == set()


def test_file_without_adjacent_text_consumes_nothing():
    by_id = {200: FileMsg(id=200)}
    assert _announcement_ids(by_id) == set()
