"""Parse a user-uploaded magazine PDF into individual articles.

A magazine issue (New Scientist, Time, The Economist, …) is one PDF with many
articles. We split it into `ParsedArticle`s so each can be stored as its own
`content_item` and dripped to the learner one per day.

Strategy — a cascading fallback that always yields something useful or raises:

  1. **TOC**        — the leading pages carry a table of contents; the LLM
                      extracts `{title, start_page}` rows and we slice pages.
                      Best for New Scientist / Time.
  2. **Boundaries** — no clean TOC, so the LLM marks article starts/ends from
                      per-page previews. Handles multi-page articles.
  3. **Page**       — deterministic last resort: each substantial, mostly-Latin
                      page is its own article. Needs no LLM and never fails on
                      "1 page = 1 article" magazines.

The pure helpers (`extract_pages`, `split_by_*`) are unit-tested with the stub
LLM (which returns empty TOC/boundary payloads, exercising the page fallback).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tutor.eval.schemas import ArticleBoundariesPayload, TocPayload
from tutor.interfaces.llm import LLMClient

# Page-text "is English prose" heuristic. Duplicated from telegram_scraper to
# keep this ingestor independent (it must not import the Telethon-based module).
_MIN_LATIN = 0.5


def _latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters)


class PdfParseError(Exception):
    """Raised when a PDF cannot be turned into any article.

    The `kind` attribute carries a short machine-readable reason
    ("encrypted", "no-text", "no-articles", "corrupt") so callers can report a
    precise message to the learner.
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        self.kind = kind
        super().__init__(detail or kind)


@dataclass(frozen=True)
class PageText:
    page_num: int  # 1-based, matches the PDF's own page numbers
    text: str


@dataclass(frozen=True)
class ParsedArticle:
    title: str
    body_text: str
    page_start: int
    page_end: int


# ---------------------------------------------------------------------------
# Page extraction (pymupdf)
# ---------------------------------------------------------------------------


def extract_pages(pdf_path: Path) -> list[PageText]:
    """Return the non-empty pages of a PDF as plain text.

    Raises `PdfParseError("encrypted")` for password-protected PDFs and
    `PdfParseError("corrupt")` if pymupdf cannot open the file at all.
    """
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise PdfParseError("corrupt", "pymupdf is not installed") from exc

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:  # noqa: BLE001 - pymupdf raises its own types
        raise PdfParseError("corrupt", str(exc)[:200]) from exc

    if getattr(doc, "needs_pass", False):
        doc.close()
        raise PdfParseError("encrypted")

    pages: list[PageText] = []
    try:
        for i, page in enumerate(doc):
            text = page.get_text("text").strip()  # "text" preserves reading order
            if text:
                pages.append(PageText(page_num=i + 1, text=text))
    finally:
        doc.close()
    return pages


# ---------------------------------------------------------------------------
# Strategy 1: table of contents
# ---------------------------------------------------------------------------

_TOC_SYSTEM = (
    "You are a PDF table-of-contents parser. Given the text of the first few "
    "pages of a magazine or journal, extract the table of contents entries.\n\n"
    "RULES:\n"
    "- Look for patterns: page number followed by title, or title followed by "
    "page number (e.g. '8 A Judge Declared...', 'A Judge Declared... 8', "
    "'Page 8: A Judge Declared...').\n"
    "- Ignore ads, running headers/footers, standalone page numbers, and bare "
    "section labels like 'FEATURES'.\n"
    "- Titles must be 5-100 characters and meaningful.\n"
    "- Page numbers must be positive integers.\n"
    "- If there is no table of contents, return has_toc=false with empty entries."
)


def _toc_user(head_pages: list[PageText]) -> str:
    blob = "\n\n".join(f"--- PAGE {p.page_num} ---\n{p.text[:2000]}" for p in head_pages)
    return f"INPUT (first pages of the PDF):\n{blob}\n\nReturn the JSON TOC."


async def parse_toc(pages: list[PageText], llm: LLMClient, *, toc_pages: int) -> TocPayload:
    """Ask the LLM to read the leading pages and return the TOC, if any."""
    head = pages[: max(1, toc_pages)]
    return await llm.complete_json(_TOC_SYSTEM, _toc_user(head), TocPayload)


def split_by_toc(pages: list[PageText], entries: list, *, min_chars: int) -> list[ParsedArticle]:
    """Slice `pages` into articles using TOC entry start pages.

    Each article spans [start_page, next_entry.start_page - 1]. Entries with
    out-of-range start pages are dropped; articles shorter than `min_chars` are
    discarded (they are usually ads or TOC residue).
    """
    by_num = {p.page_num: p for p in pages}
    if not by_num:
        return []
    max_num = max(by_num)
    valid = sorted(
        (e for e in entries if getattr(e, "start_page", 0) and 1 <= e.start_page <= max_num),
        key=lambda e: e.start_page,
    )
    articles: list[ParsedArticle] = []
    for i, entry in enumerate(valid):
        start = entry.start_page
        end = valid[i + 1].start_page - 1 if i + 1 < len(valid) else max_num
        if end < start:
            continue
        body = "\n\n".join(by_num[n].text for n in range(start, end + 1) if n in by_num).strip()
        if len(body) >= min_chars:
            title = (getattr(entry, "title", "") or "").strip() or f"Article p.{start}"
            articles.append(
                ParsedArticle(title=title[:200], body_text=body, page_start=start, page_end=end)
            )
    return articles


# ---------------------------------------------------------------------------
# Strategy 2: LLM article-boundary detection
# ---------------------------------------------------------------------------

_BOUNDARY_SYSTEM = (
    "You are a PDF article boundary detector. Given a short text preview of "
    "every page of a magazine, identify where each article starts and ends.\n\n"
    "RULES:\n"
    "- An article starts when a new prominent title appears (ALL CAPS, large "
    "text, or title-case at the top of a page).\n"
    "- Skip cover pages, ads, the table of contents, blank pages, and "
    "photo-only pages.\n"
    "- Each article must span at least one page; group consecutive pages "
    "without a new title under the previous article.\n"
    "- Section headers (e.g. TITANS, INNOVATORS) are NOT article titles.\n"
    "- `end_page` is inclusive and must be >= `start_page`."
)


def _boundary_user(pages: list[PageText]) -> str:
    previews = [{"page_num": p.page_num, "preview": p.text[:200]} for p in pages]
    joined = json.dumps(previews, ensure_ascii=False)
    return f"INPUT (per-page previews):\n{joined}\n\nReturn article boundaries."


async def detect_boundaries(pages: list[PageText], llm: LLMClient) -> ArticleBoundariesPayload:
    """Ask the LLM to mark article spans from per-page previews."""
    user = _boundary_user(pages)
    return await llm.complete_json(_BOUNDARY_SYSTEM, user, ArticleBoundariesPayload)


def split_by_boundaries(
    pages: list[PageText], articles: list, *, min_chars: int
) -> list[ParsedArticle]:
    """Materialize articles from LLM-detected `{start_page, end_page}` spans."""
    by_num = {p.page_num: p for p in pages}
    out: list[ParsedArticle] = []
    for art in articles:
        start = getattr(art, "start_page", None)
        end = getattr(art, "end_page", start)
        if not start or start not in by_num:
            continue
        end = max(start, end if end in by_num else start)
        body = "\n\n".join(by_num[n].text for n in range(start, end + 1) if n in by_num).strip()
        if len(body) >= min_chars:
            title = (getattr(art, "title", "") or "").strip() or f"Article p.{start}"
            out.append(
                ParsedArticle(title=title[:200], body_text=body, page_start=start, page_end=end)
            )
    return out


# ---------------------------------------------------------------------------
# Strategy 3: deterministic page-per-article (fallback)
# ---------------------------------------------------------------------------


def split_by_page(pages: list[PageText], *, min_chars: int) -> list[ParsedArticle]:
    """Treat each substantial, mostly-English page as its own article.

    The reliable last resort for '1 page = 1 article' magazines and whenever
    the LLM strategies come back empty.
    """
    articles: list[ParsedArticle] = []
    for p in pages:
        body = p.text.strip()
        if len(body) >= min_chars and _latin_ratio(body) >= _MIN_LATIN:
            title = body.splitlines()[0][:120]
            articles.append(
                ParsedArticle(
                    title=title, body_text=body, page_start=p.page_num, page_end=p.page_num
                )
            )
    return articles


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def parse_pdf(
    pdf_path: Path,
    llm: LLMClient,
    *,
    max_articles: int = 10,
    toc_pages: int = 5,
    min_chars: int = 350,
) -> list[ParsedArticle]:
    """Parse a PDF into up to `max_articles` articles using the cascade.

    Always returns at least one article or raises `PdfParseError`. LLM failures
    (timeouts, bad JSON) are swallowed and fall through to the deterministic
    page strategy, which needs no model.
    """
    pages = extract_pages(pdf_path)
    if not pages or sum(len(p.text) for p in pages) < min_chars:
        # No text layer at all → likely a scanned/image-only PDF (needs OCR).
        raise PdfParseError("no-text")

    # 1. TOC
    try:
        toc = await parse_toc(pages, llm, toc_pages=toc_pages)
        if toc.has_toc and toc.entries:
            arts = split_by_toc(pages, toc.entries, min_chars=min_chars)
            if arts:
                return arts[:max_articles]
    except Exception:  # noqa: BLE001 - LLM flakiness falls through to the next strategy
        pass

    # 2. Boundary detection
    try:
        bounds = await detect_boundaries(pages, llm)
        if bounds.articles:
            arts = split_by_boundaries(pages, bounds.articles, min_chars=min_chars)
            if arts:
                return arts[:max_articles]
    except Exception:  # noqa: BLE001
        pass

    # 3. Deterministic page-per-article
    arts = split_by_page(pages, min_chars=min_chars)
    if arts:
        return arts[:max_articles]

    raise PdfParseError("no-articles")
