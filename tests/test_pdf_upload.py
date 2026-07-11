"""End-to-end ingest of a generated PDF into the repository (no aiogram).

This is where the real logic lives that the Telegram handler is thin glue
around: parsing -> storage with the right source_ref/external_id, and dedup on
re-upload. PDFs are generated on the fly with pymupdf.
"""

from __future__ import annotations

from tutor.adapters.llm.stub import StubLLMClient
from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.domain.enums import ContentType, DeliveryStatus, SourceType
from tutor.ingest.pdf_upload import ingest_pdf_bytes, source_ref_for

_USER = 764315256  # matches the subscriber the `repo` fixture ensures

_PARAGRAPH = (
    "Climate scientists have long warned that rising sea levels threaten "
    "coastal cities around the world. Recent measurements confirm the trend "
    "and narrow the uncertainty in the projections for the coming decades. "
)


def _english(variant: int = 0) -> str:
    # Each variant produces a distinct body so body-hash dedup does not collapse
    # different pages of the same issue into one (real magazine pages differ).
    return _PARAGRAPH * 2 + f" Variant {variant} adds a unique marker to this page."


def _pdf_bytes(pages: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(page.rect, body, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _settings() -> Settings:
    # Keep test pages comfortably above the threshold without huge fixtures.
    return Settings(pdf_min_article_chars=100, pdf_toc_pages=2, pdf_articles_per_issue=10)


def test_source_ref_is_stable_and_short() -> None:
    ref1 = source_ref_for(b"abc")
    ref2 = source_ref_for(b"abc")
    ref3 = source_ref_for(b"different bytes")
    assert ref1 == ref2 == "pdf:ba7816bf"  # first 8 hex of sha256('abc')
    assert ref1 != ref3
    assert ref1.startswith("pdf:") and len(ref1) == len("pdf:") + 8


async def test_ingest_pdf_bytes_queues_one_article_per_page(repo: Repository) -> None:
    pdf = _pdf_bytes([_english(1), _english(2), _english(3)])
    report = await ingest_pdf_bytes(_settings(), repo, StubLLMClient(), _USER, pdf, "issue.pdf")

    assert (report.parsed, report.stored, report.skipped_dup) == (3, 3, 0)
    assert report.issue.startswith("pdf:")

    new = repo.fetch_by_status(_USER, DeliveryStatus.NEW)
    assert len(new) == 3
    assert {item.source_type for item in new} == {SourceType.UPLOAD}
    assert {item.external_id for item in new} == {"p1", "p2", "p3"}
    assert all(item.content_type == ContentType.ARTICLE for item in new)
    assert all(item.source_ref == report.issue for item in new)


async def test_reupload_same_pdf_is_a_noop(repo: Repository) -> None:
    pdf = _pdf_bytes([_english(1), _english(2)])
    settings = _settings()
    first = await ingest_pdf_bytes(settings, repo, StubLLMClient(), _USER, pdf, "issue.pdf")
    second = await ingest_pdf_bytes(settings, repo, StubLLMClient(), _USER, pdf, "issue.pdf")

    assert first.stored == 2
    assert second.stored == 0
    assert second.skipped_dup == 2
    # No duplicate rows appeared.
    assert len(repo.fetch_by_status(_USER, DeliveryStatus.NEW)) == 2
