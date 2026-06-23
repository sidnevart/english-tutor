"""Tests for PDF parsing: extract_pages, parse_toc, split_by_toc, split_by_llm."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tutor.adapters.llm.stub import StubLLMClient
from tutor.ingest.pdf_parser import (
    Article,
    PageText,
    TocEntry,
    _extract_toc_entries_regex,
    extract_pages,
    parse_pdf,
    parse_toc,
    split_by_toc,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> list[PageText]:
    """Load page texts from a JSON fixture file."""
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"Fixture {name} not found")
    data = json.loads(path.read_text())
    return [PageText(page_num=p["page_num"], text=p["text"]) for p in data]


def _ns_pages() -> list[PageText]:
    return _load_fixture("new_scientist_pages_1_10.json")


def _time_pages() -> list[PageText]:
    return _load_fixture("time_pages_1_10.json")


# ---------------------------------------------------------------------------
# Regex TOC parsing
# ---------------------------------------------------------------------------


def test_extract_toc_regex_new_scientist():
    """Should extract TOC entries from New Scientist TOC page."""
    pages = _ns_pages()
    if len(pages) < 3:
        pytest.skip("Not enough pages in fixture")

    # Page 3 (index 2) is the TOC in New Scientist.
    toc_text = pages[2].text
    entries = _extract_toc_entries_regex(toc_text)

    # Should find multiple entries.
    assert len(entries) >= 5, f"Expected >= 5 TOC entries, got {len(entries)}"

    # All entries should have valid page numbers.
    for e in entries:
        assert e.start_page > 0
        assert len(e.title) >= 5

    # Check known New Scientist articles.
    titles = [e.title.lower() for e in entries]
    combined = " ".join(titles)
    assert any(
        word in combined for word in ["hiding", "quantum", "sharp", "killer", "drones", "whale"]
    ), f"No expected topics found in: {titles}"


def test_extract_toc_regex_time():
    """Should extract TOC entries from Time TOC page."""
    pages = _time_pages()
    if len(pages) < 3:
        pytest.skip("Not enough pages in fixture")

    # Page 3 (index 2) is the TOC in Time.
    toc_text = pages[2].text
    entries = _extract_toc_entries_regex(toc_text)

    assert len(entries) >= 3, f"Expected >= 3 TOC entries, got {len(entries)}"

    # Check that known Time articles are found.
    titles = [e.title.lower() for e in entries]
    combined = " ".join(titles)
    assert any(
        word in combined for word in ["judge", "vaccine", "dietary", "doctor", "health", "cancer"]
    ), f"No expected topics found in: {titles}"


def test_extract_toc_regex_empty_text():
    """Empty text should return no entries."""
    assert _extract_toc_entries_regex("") == []


def test_extract_toc_regex_no_toc():
    """Text without TOC pattern should return few or no entries."""
    text = "This is just a regular paragraph about science and discovery."
    entries = _extract_toc_entries_regex(text)
    assert len(entries) == 0


# ---------------------------------------------------------------------------
# LLM TOC parsing
# ---------------------------------------------------------------------------


async def test_parse_toc_with_stub():
    """Stub LLM should not crash parse_toc."""
    pages = _ns_pages()
    if not pages:
        pytest.skip("No fixture data")

    entries = await parse_toc(pages, StubLLMClient())
    # Stub may return empty or regex results — that's fine.
    assert isinstance(entries, list)


# ---------------------------------------------------------------------------
# Split by TOC
# ---------------------------------------------------------------------------


def test_split_by_toc_basic():
    """split_by_toc should create articles from TOC entries and pages."""
    pages = [
        PageText(1, "Cover page"),
        PageText(2, "TOC: Article A on page 3"),
        PageText(3, "Article A content here. " * 50),
        PageText(4, "Article A continued. " * 50),
        PageText(5, "Article B content here. " * 50),
    ]
    toc = [
        TocEntry(title="Article A", start_page=3),
        TocEntry(title="Article B", start_page=5),
    ]

    articles = split_by_toc(pages, toc)

    assert len(articles) == 2
    assert articles[0].title == "Article A"
    assert articles[0].page_start == 3
    assert articles[0].page_end == 4
    assert articles[1].title == "Article B"
    assert articles[1].page_start == 5
    assert articles[1].page_end == 5


def test_split_by_toc_empty_toc():
    """Empty TOC should return no articles."""
    pages = [PageText(1, "Some text")]
    assert split_by_toc(pages, []) == []


def test_split_by_toc_skips_short_articles():
    """Articles with less than 200 chars should be skipped."""
    pages = [
        PageText(1, "Short"),
        PageText(2, "B"),
    ]
    toc = [
        TocEntry(title="Tiny", start_page=1),
        TocEntry(title="Also tiny", start_page=2),
    ]
    articles = split_by_toc(pages, toc)
    assert len(articles) == 0


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


async def test_parse_pdf_no_file():
    """parse_pdf with nonexistent file should return empty."""
    result = await parse_pdf(Path("/tmp/nonexistent.pdf"), StubLLMClient())
    assert result == []


# ---------------------------------------------------------------------------
# Extract pages from real PDFs
# ---------------------------------------------------------------------------


def test_extract_pages_real_new_scientist():
    """Should extract pages from the real New Scientist PDF."""
    pdf_path = Path("/tmp/new_scientist.pdf")
    if not pdf_path.exists():
        pytest.skip("New Scientist PDF not downloaded")

    pages = extract_pages(pdf_path)
    assert len(pages) >= 40, f"Expected >= 40 pages, got {len(pages)}"

    # First non-empty page should have content.
    assert any(len(p.text) > 100 for p in pages[:5])


def test_extract_pages_real_time():
    """Should extract pages from the real Time PDF."""
    pdf_path = Path("/tmp/time_health.pdf")
    if not pdf_path.exists():
        pytest.skip("Time PDF not downloaded")

    pages = extract_pages(pdf_path)
    assert len(pages) >= 50, f"Expected >= 50 pages, got {len(pages)}"


# ---------------------------------------------------------------------------
# Scraper integration
# ---------------------------------------------------------------------------


def test_scraper_pdf_detection():
    """_is_pdf should detect PDF messages."""
    from tutor.ingest.telegram_scraper import _is_pdf

    # Mock message with PDF.
    class MockDoc:
        mime_type = "application/pdf"

    class MockMedia:
        document = MockDoc()

    class MockMsg:
        media = MockMedia()

    assert _is_pdf(MockMsg()) is True

    # Mock message without media.
    class NoMediaMsg:
        media = None

    assert _is_pdf(NoMediaMsg()) is False

    # Mock message with non-PDF.
    class NonPdfDoc:
        mime_type = "image/png"

    class NonPdfMedia:
        document = NonPdfDoc()

    class NonPdfMsg:
        media = NonPdfMedia()

    assert _is_pdf(NonPdfMsg()) is False


def test_scraper_pdf_to_rawitem():
    """_pdf_to_rawitem should convert Article to RawItem."""
    from tutor.ingest.telegram_scraper import _pdf_to_rawitem

    article = Article(
        title="Test Article",
        body_text="Content here.",
        page_start=5,
        page_end=7,
    )
    raw = _pdf_to_rawitem(article, channel_id=1137165265, msg_id=9632)

    assert raw.source_type.value == "channel"
    assert raw.external_id == "9632_p5"
    assert raw.title == "Test Article"
    assert raw.body_text == "Content here."
    assert "9632" in raw.url
