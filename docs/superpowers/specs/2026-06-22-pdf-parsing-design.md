# PDF Parsing Pipeline — Design Spec

## Problem

The Telegram channel @muscatnonfiction (Books in English) posts magazine PDFs (New Scientist, Time, etc.) containing 60-100 pages, each page being a separate article. The current scraper only handles text messages and ignores PDFs entirely. We need a generic PDF parser that works for any magazine/journal PDF with a table of contents.

## User Flow

```
Channel post with PDF → Scraper detects PDF → Downloads → Extracts pages
→ Parses TOC → Splits into articles → Stores each as content_item
→ Morning push delivers individual articles → Quiz + flashcards as usual
```

## PDF Patterns Observed

| Magazine | Pages | Structure | TOC |
|----------|-------|-----------|-----|
| New Scientist | 53 | 1 page = 1 article | Page 2, page numbers + titles |
| Time Special Edition | 101 | Articles span 2-4 pages | Page 2, page numbers + titles |
| Adobe Photoshop Guide | N/A | Book chapters (not articles) | Different format — skip |

**Common pattern**: TOC on page 2-3 with format `{page_num} {title}` or `{title} {page_num}`.

## Architecture

### New module: `ingest/pdf_parser.py`

```python
async def parse_pdf(
    pdf_path: Path,
    llm: LLMClient,
    *,
    max_articles: int = 10,
) -> list[dict]:
    """Parse a PDF into individual articles.

    Returns a list of dicts with keys:
    - title: str
    - body_text: str (concatenated page text)
    - page_start: int
    - page_end: int
    """
```

### Functions

1. **`extract_pages(pdf_path)`** — use pymupdf to extract text from each page
   - Returns: `list[dict]` with `page_num` and `text`
   - Skips empty pages (ads, blank backs)

2. **`parse_toc(pages, llm)`** — LLM parses the table of contents
   - Input: text of pages 1-5
   - Output: `list[dict]` with `title` and `start_page`
   - Uses `complete_json()` with `TocPayload` schema

3. **`split_by_toc(pages, toc_entries)`** — split pages into articles using TOC
   - Each article = pages from `start_page` to next article's `start_page - 1`
   - Returns: `list[dict]` with `title`, `body_text`, `page_start`, `page_end`

4. **`split_by_llm(pages, llm)`** — fallback when no TOC found
   - Sends all page title previews to LLM
   - LLM returns article boundaries
   - Uses `complete_json()` with `ArticleBoundariesPayload` schema

### Integration with scraper

In `telegram_scraper.py`, `scrape_channel()` is modified:

```python
async for msg in client.iter_messages(channel, limit=limit):
    if _is_pdf(msg):
        articles = await parse_pdf_from_message(client, msg, llm)
        for article in articles:
            raw = _pdf_to_rawitem(article, channel_id, msg.id)
            if repo.add_content(raw, user_id) is not None:
                stored += 1
    else:
        raw = normalize(msg, channel_id)
        if raw and is_suitable(raw):
            if repo.add_content(raw, user_id) is not None:
                stored += 1
```

## Data Flow

```
Telegram message with PDF
  → download_media() → /tmp/{channel_id}_{msg_id}.pdf
  → pymupdf: extract text per page → [{page_num, text}, ...]
  → LLM: parse TOC → [{title, start_page}, ...]
  → split_by_toc() → [{title, body_text, page_start, page_end}, ...]
  → for each article:
      → RawItem(
            source_type=CHANNEL,
            source_ref=str(channel_id),
            external_id=f"{msg_id}_p{page_start}",
            content_type=ARTICLE,
            title=article.title,
            url=f"https://t.me/c/{short_id}/{msg_id}",
            body_text=article.body_text,
        )
      → add_content() → content_item table
```

## LLM Prompts

### TOC Parser

```
You are a PDF table-of-contents parser. Given the text of the first few pages
of a magazine or journal, extract the table of contents entries.

INPUT: text of pages 1-5 of a PDF

OUTPUT (JSON):
{
  "has_toc": true,
  "entries": [
    {"title": "Article title here", "start_page": 8},
    {"title": "Another article", "start_page": 12}
  ]
}

RULES:
- Look for patterns: page number followed by title, or title followed by page number
- Ignore ads, headers, footers, standalone page numbers
- Titles should be 5-100 characters, meaningful (not section headers like "FEATURES")
- Page numbers must be positive integers
- If no TOC is found, return {"has_toc": false, "entries": []}
- Common TOC formats:
  - "8 A Judge Declared the Government's Vaccine Rollbacks"
  - "A Judge Declared... 8"
  - "Page 8: A Judge Declared..."
```

### Article Boundary Detector (fallback)

```
You are a PDF article boundary detector. Given the text previews of each page
of a magazine, identify where each article starts and ends.

INPUT: list of {page_num, text_preview (first 200 chars)} for all pages

OUTPUT (JSON):
{
  "articles": [
    {"title": "Article title", "start_page": 4, "end_page": 6},
    {"title": "Another article", "start_page": 7, "end_page": 7}
  ]
}

RULES:
- An article starts when a new prominent title appears (ALL CAPS, large text,
  or title-case at the top of a page)
- Skip: cover pages, ads, table of contents, blank pages, photo-only pages
- Each article must have at least 300 characters of actual text
- Group consecutive pages that don't have a new title under the previous article
- Section headers (TITANS, INNOVATORS, CATALYSTS) are NOT article titles
```

## Config Additions

```python
pdf_max_size_mb: int = 100       # max PDF size to download
pdf_articles_per_issue: int = 10  # max articles per PDF (first N, skip covers/ads)
pdf_toc_pages: int = 5            # how many pages to check for TOC
```

## Dependencies

- `pymupdf` (package: `PyMuPDF`) — fast PDF text extraction
- No new external APIs

## Testing Strategy

### Unit tests (CI-safe)

- `test_extract_pages` — extract text from a small test PDF
- `test_parse_toc_new_scientist` — parse TOC from known text
- `test_parse_toc_time` — parse TOC from Time format
- `test_split_by_toc` — verify article boundaries
- `test_no_toc_returns_empty` — handle missing TOC

### Eval tests (real LLM)

- `test_toc_parsing_accuracy` — parse TOC from 3 real PDFs, compare with manual annotation
- `test_article_boundary_accuracy` — verify articles split correctly
- `test_article_text_quality` — verify extracted text is readable

### Test data

Store extracted page texts (not full PDFs) in `tests/fixtures/` for CI tests:
- `new_scientist_pages_1_5.txt` — first 5 pages of New Scientist
- `time_pages_1_5.txt` — first 5 pages of Time

## File Structure

```
src/tutor/ingest/
├── pdf_parser.py          # NEW: PDF parsing logic
├── telegram_scraper.py    # MODIFIED: PDF detection
└── rss.py                 # unchanged

tests/
├── test_pdf_parser.py     # NEW: unit tests
├── eval_pdf_parsing.py    # NEW: eval tests
└── fixtures/
    ├── new_scientist_pages_1_5.txt
    └── time_pages_1_5.txt
```

## Error Handling

- PDF too large (> max_size_mb) → skip, log warning
- pymupdf extraction fails → skip, log error
- No TOC found AND LLM boundary detection fails → skip PDF, log error
- Article too short (< 300 chars) → skip that article
- Article too long (> max_article_len) → truncate
- Network error during download → retry once, then skip
