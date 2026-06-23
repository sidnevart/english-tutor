"""PDF parsing: extract articles from magazine-style PDFs.

Handles two patterns:
  1. TOC-based: parse table of contents from first pages, split by page numbers
  2. LLM fallback: when no TOC found, use LLM to detect article boundaries

Each extracted article becomes a RawItem ready for add_content().
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from tutor.interfaces.llm import LLMClient


@dataclass
class PageText:
    """Text extracted from a single PDF page."""

    page_num: int  # 1-based
    text: str


@dataclass
class Article:
    """An article extracted from a PDF."""

    title: str
    body_text: str
    page_start: int
    page_end: int


class TocEntry(BaseModel):
    title: str
    start_page: int = Field(gt=0)


class TocPayload(BaseModel):
    has_toc: bool = False
    entries: list[TocEntry] = Field(default_factory=list)


class ArticleBoundary(BaseModel):
    title: str
    start_page: int = Field(gt=0)
    end_page: int = Field(gt=0)


class ArticleBoundariesPayload(BaseModel):
    articles: list[ArticleBoundary] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 1: Extract text from PDF pages
# ---------------------------------------------------------------------------


def extract_pages(pdf_path: Path) -> list[PageText]:
    """Extract text from each page of a PDF using pymupdf.

    Returns a list of PageText objects (1-based page numbers).
    Skips empty pages. Returns empty list if file not found or unreadable.
    """
    import pymupdf

    try:
        doc = pymupdf.open(str(pdf_path))
    except (FileNotFoundError, pymupdf.FileNotFoundError):
        return []

    pages: list[PageText] = []
    try:
        for i in range(len(doc)):
            page = doc[i]
            text = page.get_text("text").strip()
            if text:  # skip empty/blank pages
                pages.append(PageText(page_num=i + 1, text=text))
    finally:
        doc.close()
    return pages


# ---------------------------------------------------------------------------
# Step 2: Parse table of contents
# ---------------------------------------------------------------------------

# Common TOC patterns: "8 Title here" or "Title here ... 8"
_TOC_PATTERN_NUM_FIRST = re.compile(r"^\s*(\d{1,3})\s+([A-Z].{8,80})\s*$", re.MULTILINE)
_TOC_PATTERN_NUM_LAST = re.compile(r"^\s*([A-Z].{8,80})\s+(\d{1,3})\s*$", re.MULTILINE)


def _extract_toc_entries_regex(text: str) -> list[TocEntry]:
    """Try to extract TOC entries using regex (fast, deterministic)."""
    entries: list[TocEntry] = []

    # Try "number first" pattern.
    for m in _TOC_PATTERN_NUM_FIRST.finditer(text):
        page_num = int(m.group(1))
        title = m.group(2).strip()
        # Filter out section headers (ALL CAPS, short).
        if len(title) > 10 and not title.isupper():
            entries.append(TocEntry(title=title, start_page=page_num))

    # If few matches, try "number last" pattern.
    if len(entries) < 3:
        for m in _TOC_PATTERN_NUM_LAST.finditer(text):
            page_num = int(m.group(2))
            title = m.group(1).strip()
            if len(title) > 10 and not title.isupper():
                entry = TocEntry(title=title, start_page=page_num)
                if entry not in entries:
                    entries.append(entry)

    # Deduplicate by start_page, keep first occurrence.
    seen_pages: set[int] = set()
    unique: list[TocEntry] = []
    for e in sorted(entries, key=lambda x: x.start_page):
        if e.start_page not in seen_pages:
            seen_pages.add(e.start_page)
            unique.append(e)

    return unique


_TOC_SYSTEM = (
    "You are a PDF table-of-contents parser. Given the text of the first few "
    "pages of a magazine or journal, extract the table of contents entries.\n\n"
    "RULES:\n"
    "- Look for patterns: page number followed by title, or title followed by "
    "page number\n"
    "- Ignore ads, headers, footers, standalone page numbers\n"
    "- Titles should be 5-100 characters, meaningful (not section headers like "
    "'FEATURES' or 'INNOVATORS')\n"
    "- Page numbers must be positive integers\n"
    '- If no TOC is found, return {"has_toc": false, "entries": []}\n'
    "- Common TOC formats:\n"
    "  '8 A Judge Declared the Government\\'s Vaccine Rollbacks'\n"
    "  'A Judge Declared... 8'\n"
    "  'Page 8: A Judge Declared...'"
)


async def parse_toc(pages: list[PageText], llm: LLMClient) -> list[TocEntry]:
    """Parse table of contents from the first pages of a PDF.

    Tries regex first (fast), falls back to LLM if few entries found.
    """
    # Combine first 5 pages for TOC detection.
    toc_text = "\n\n".join(f"--- Page {p.page_num} ---\n{p.text}" for p in pages[:5])

    # Try regex first.
    entries = _extract_toc_entries_regex(toc_text)
    if len(entries) >= 3:
        return entries

    # Fallback to LLM.
    try:
        payload = await llm.complete_json(_TOC_SYSTEM, toc_text, TocPayload)
        if payload.has_toc and payload.entries:
            return payload.entries
    except Exception:  # noqa: BLE001
        pass

    return entries  # return whatever regex found (may be empty)


# ---------------------------------------------------------------------------
# Step 3: Split pages into articles
# ---------------------------------------------------------------------------


def split_by_toc(pages: list[PageText], toc: list[TocEntry]) -> list[Article]:
    """Split pages into articles using table of contents entries.

    Each article spans from its start_page to the next article's start_page - 1.
    """
    if not toc:
        return []

    # Build page number lookup.
    page_map = {p.page_num: p.text for p in pages}
    total_pages = max(page_map.keys()) if page_map else 0

    articles: list[Article] = []
    sorted_toc = sorted(toc, key=lambda e: e.start_page)

    for i, entry in enumerate(sorted_toc):
        start = entry.start_page
        end = sorted_toc[i + 1].start_page - 1 if i + 1 < len(sorted_toc) else total_pages

        # Collect text from all pages in this article's range.
        body_parts: list[str] = []
        for pg in range(start, end + 1):
            if pg in page_map:
                body_parts.append(page_map[pg])

        body_text = "\n\n".join(body_parts).strip()
        if len(body_text) >= 200:  # skip very short articles
            articles.append(
                Article(
                    title=entry.title,
                    body_text=body_text,
                    page_start=start,
                    page_end=end,
                )
            )

    return articles


# ---------------------------------------------------------------------------
# Step 4: LLM fallback for boundary detection
# ---------------------------------------------------------------------------

_BOUNDARY_SYSTEM = (
    "You are a PDF article boundary detector. Given the text previews of each "
    "page of a magazine, identify where each article starts and ends.\n\n"
    "RULES:\n"
    "- An article starts when a new prominent title appears (ALL CAPS, large "
    "text, or title-case at the top of a page)\n"
    "- Skip: cover pages, ads, table of contents, blank pages, photo-only pages\n"
    "- Each article must have at least 300 characters of actual text\n"
    "- Group consecutive pages without a new title under the previous article\n"
    "- Section headers (TITANS, INNOVATORS, CATALYSTS, VIEWS) are NOT article "
    "titles — skip them\n"
    "- Return at most 15 articles"
)


async def split_by_llm(pages: list[PageText], llm: LLMClient) -> list[Article]:
    """Use LLM to detect article boundaries when no TOC is found.

    Sends page previews to the LLM and asks it to identify article starts.
    """
    # Build page previews (first 300 chars per page).
    previews = []
    for p in pages[:50]:  # cap at 50 pages to avoid token overflow
        preview = p.text[:300].replace("\n", " ").strip()
        previews.append(f"Page {p.page_num}: {preview}")

    user_prompt = "\n".join(previews)

    try:
        payload = await llm.complete_json(_BOUNDARY_SYSTEM, user_prompt, ArticleBoundariesPayload)
    except Exception:  # noqa: BLE001
        return []

    # Build page lookup.
    page_map = {p.page_num: p.text for p in pages}

    articles: list[Article] = []
    for ab in payload.articles:
        body_parts: list[str] = []
        for pg in range(ab.start_page, ab.end_page + 1):
            if pg in page_map:
                body_parts.append(page_map[pg])

        body_text = "\n\n".join(body_parts).strip()
        if len(body_text) >= 200:
            articles.append(
                Article(
                    title=ab.title,
                    body_text=body_text,
                    page_start=ab.start_page,
                    page_end=ab.end_page,
                )
            )

    return articles


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def parse_pdf(
    pdf_path: Path,
    llm: LLMClient,
    *,
    max_articles: int = 10,
) -> list[Article]:
    """Parse a PDF into individual articles.

    Strategy:
    1. Extract text from all pages
    2. Try to parse TOC from first pages
    3. If TOC found → split by TOC
    4. If no TOC → use LLM boundary detection
    5. Return up to max_articles articles
    """
    pages = extract_pages(pdf_path)
    if not pages:
        return []

    # Try TOC-based splitting.
    toc = await parse_toc(pages, llm)
    if toc:
        articles = split_by_toc(pages, toc)
        if articles:
            return articles[:max_articles]

    # Fallback: LLM boundary detection.
    articles = await split_by_llm(pages, llm)
    return articles[:max_articles]
