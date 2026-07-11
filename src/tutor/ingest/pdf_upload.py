"""Ingest a user-uploaded PDF issue into the content queue.

The learner sends a magazine PDF to the bot; this module parses it into
articles and stores each as a `content_item` (status=NEW, ARTICLE). Articles
from one issue share `source_ref = "pdf:{sha8}"`, so:

  * they group naturally as one issue (used by /queue), and
  * re-uploading the same file is a no-op — `repo.add_content` is idempotent on
    `(source_ref, external_id)` and on the body hash.

The morning push then drips them ~1/day through the *existing* delivery path;
no new delivery/quiz/anki logic lives here.
"""

from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path

from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.pdf_parser import ParsedArticle, parse_pdf


@dataclass(frozen=True)
class PdfIngestReport:
    issue: str  # "pdf:a1b2c3d4" — shared by every article from this PDF
    parsed: int  # articles the parser produced
    stored: int  # newly stored (non-duplicate) articles
    skipped_dup: int  # articles already present (re-upload)


def source_ref_for(pdf_bytes: bytes) -> str:
    """Stable issue id: first 8 hex chars of the PDF's SHA-256."""
    return f"pdf:{hashlib.sha256(pdf_bytes).hexdigest()[:8]}"


def _to_raw(article: ParsedArticle, issue: str, filename: str) -> RawItem:
    return RawItem(
        source_type=SourceType.UPLOAD,
        source_ref=issue,
        external_id=f"p{article.page_start}",  # unique within the issue
        content_type=ContentType.ARTICLE,
        title=article.title or f"{filename} p.{article.page_start}",
        url="",
        body_text=article.body_text,
    )


async def ingest_pdf_bytes(
    settings: Settings,
    repo: Repository,
    llm: object,
    user_id: int,
    pdf_bytes: bytes,
    filename: str,
) -> PdfIngestReport:
    """Parse `pdf_bytes` and queue its articles. Raises `PdfParseError` on
    unrecoverable PDF problems (encrypted, scanned, empty); the caller reports
    those to the learner."""
    issue = source_ref_for(pdf_bytes)

    # pymupdf works most reliably with a path, so spill the bytes to a temp file.
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)
    try:
        articles = await parse_pdf(
            tmp_path,
            llm,
            max_articles=settings.pdf_articles_per_issue,
            toc_pages=settings.pdf_toc_pages,
            min_chars=settings.pdf_min_article_chars,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    stored = 0
    skipped = 0
    for art in articles:
        raw = _to_raw(art, issue, filename)
        if repo.add_content(raw, user_id) is not None:
            stored += 1
        else:
            skipped += 1
    return PdfIngestReport(issue=issue, parsed=len(articles), stored=stored, skipped_dup=skipped)
