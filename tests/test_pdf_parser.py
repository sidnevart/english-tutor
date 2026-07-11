"""Unit tests for the PDF parser.

CI-safe: the stub LLM returns empty TOC/boundary payloads, which exercises the
deterministic page fallback; a tiny fake LLM exercises the TOC strategy. Real
PDFs are generated on the fly with pymupdf (no binary fixtures in the repo).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tutor.adapters.llm.stub import StubLLMClient
from tutor.eval.schemas import TocEntry, TocPayload
from tutor.ingest.pdf_parser import (
    PageText,
    PdfParseError,
    extract_pages,
    parse_pdf,
    split_by_page,
    split_by_toc,
)

_PARAGRAPH = (
    "Climate scientists have long warned that rising sea levels threaten "
    "coastal cities around the world. Recent measurements confirm the trend "
    "and narrow the uncertainty in the projections for the coming decades. "
)


def _english(repeat: int = 2) -> str:
    return _PARAGRAPH * repeat


def _build_pdf(path: Path, pages: list[str]) -> None:
    import pymupdf

    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(page.rect, body, fontsize=11)
    doc.save(path)
    doc.close()


class _FakeTOCLLM:
    """Returns a fixed payload so the TOC strategy can be exercised in tests."""

    def __init__(self, payload: TocPayload) -> None:
        self._payload = payload

    async def complete(self, system: str, user: str) -> str:
        return "fake"

    async def complete_json(self, system, user, schema):  # type: ignore[no-untyped-def]
        return self._payload


# ---------------------------------------------------------------------------
# extract_pages
# ---------------------------------------------------------------------------


def test_extract_pages_returns_one_pagetext_per_nonempty_page(tmp_path: Path) -> None:
    pdf = tmp_path / "issue.pdf"
    _build_pdf(pdf, [_english(), _english(), _english()])
    pages = extract_pages(pdf)
    assert [p.page_num for p in pages] == [1, 2, 3]
    assert all(p.text.strip() for p in pages)


def test_extract_pages_raises_on_corrupt_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a real pdf")
    with pytest.raises(PdfParseError) as exc:
        extract_pages(bad)
    assert exc.value.kind == "corrupt"


# ---------------------------------------------------------------------------
# split_by_page (deterministic fallback)
# ---------------------------------------------------------------------------


def test_split_by_page_keeps_long_english_pages_only() -> None:
    pages = [
        PageText(1, _english()),  # long + English -> kept
        PageText(2, "too short"),  # under min_chars -> dropped
        PageText(3, "короткий русский текст " * 40),  # not Latin -> dropped
    ]
    arts = split_by_page(pages, min_chars=100)
    assert len(arts) == 1
    assert arts[0].page_start == 1 and arts[0].page_end == 1


# ---------------------------------------------------------------------------
# split_by_toc
# ---------------------------------------------------------------------------


def test_split_by_toc_drops_out_of_range_entries_and_spans_pages() -> None:
    pages = [PageText(i, _english()) for i in range(1, 5)]
    entries = [
        TocEntry(title="A", start_page=1),
        TocEntry(title="B", start_page=99),  # out of range -> dropped
        TocEntry(title="C", start_page=3),
    ]
    arts = split_by_toc(pages, entries, min_chars=100)
    assert [(a.title, a.page_start, a.page_end) for a in arts] == [
        ("A", 1, 2),
        ("C", 3, 4),
    ]


# ---------------------------------------------------------------------------
# parse_pdf (orchestrator cascade)
# ---------------------------------------------------------------------------


async def test_parse_pdf_stub_falls_through_to_page_strategy(tmp_path: Path) -> None:
    pdf = tmp_path / "issue.pdf"
    _build_pdf(pdf, [_english(), _english(), _english(), _english()])
    arts = await parse_pdf(pdf, StubLLMClient(), max_articles=10, toc_pages=2, min_chars=100)
    # Stub returns empty TOC/boundaries -> one article per page.
    assert [a.page_start for a in arts] == [1, 2, 3, 4]


async def test_parse_pdf_uses_toc_when_available(tmp_path: Path) -> None:
    pdf = tmp_path / "issue.pdf"
    _build_pdf(pdf, [_english(), _english(), _english(), _english()])
    toc = TocPayload(
        has_toc=True,
        entries=[TocEntry(title="First", start_page=1), TocEntry(title="Second", start_page=3)],
    )
    arts = await parse_pdf(pdf, _FakeTOCLLM(toc), max_articles=10, toc_pages=2, min_chars=100)
    assert len(arts) == 2  # grouped by TOC, not 1-per-page
    assert arts[0].title == "First"
    assert (arts[0].page_start, arts[0].page_end) == (1, 2)
    assert (arts[1].page_start, arts[1].page_end) == (3, 4)


async def test_parse_pdf_respects_max_articles(tmp_path: Path) -> None:
    pdf = tmp_path / "issue.pdf"
    _build_pdf(pdf, [_english()] * 5)
    arts = await parse_pdf(pdf, StubLLMClient(), max_articles=3, toc_pages=2, min_chars=100)
    assert len(arts) == 3


async def test_parse_pdf_raises_on_no_text(tmp_path: Path) -> None:
    pdf = tmp_path / "scanned.pdf"
    _build_pdf(pdf, ["", "", ""])  # blank pages -> no text layer
    with pytest.raises(PdfParseError) as exc:
        await parse_pdf(pdf, StubLLMClient(), min_chars=100)
    assert exc.value.kind == "no-text"
