"""Telegram channel scraping via a Telethon userbot.

The existing bot_data session is a Telethon session, so we reuse it directly.
The pure `normalize` (message -> RawItem) is unit-tested; the Telethon client
IO is isolated in `run_scrape`, which needs TG_API_ID/TG_API_HASH and the
`scrape` extra installed.

Supported attachment types:
  - PDF  → pdf_parser.parse_pdf (LLM-assisted TOC / boundary detection)
  - EPUB → zipfile extraction of xhtml chapters (no extra dependencies)
  - Text messages → normalized directly

Watermark-based scraping:
  Each channel tracks (max_scraped_id, min_scraped_id) in the DB.
  Every run does two phases:
    1. New messages   — id > max_scraped_id  (picks up today's posts)
    2. History batch  — id < min_scraped_id, limit=scrape_history_batch
                        (gradually backfills months of past content)
  First run: fetches `scrape_history_batch` most recent messages and sets
  both watermarks from the result.
"""

from __future__ import annotations

import html as html_lib
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem


def _short_id(channel_id: int) -> int:
    """Telegram t.me/c links use the channel id without the -100 prefix."""
    s = str(channel_id)
    if s.startswith("-100"):
        return int(s[4:])
    return abs(channel_id)


def _marked_id(channel_id: int) -> int:
    """Telethon resolves channels by their -100-prefixed 'marked' id."""
    s = str(channel_id)
    if s.startswith("-100") or channel_id < 0:
        return channel_id
    return int(f"-100{channel_id}")


def _latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters)


def is_suitable(
    raw: RawItem,
    *,
    min_len: int = 350,
    max_len: int = 4500,
    min_latin: float = 0.5,
) -> bool:
    """Keep only mid-length, predominantly-English posts. Drops short
    blurbs/ads and overly long articles (not TOEFL-scale passages)."""
    body = raw.body_text.strip()
    return min_len <= len(body) <= max_len and _latin_ratio(body) >= min_latin


def normalize(msg: Any, channel_id: int) -> RawItem | None:
    """Convert a Telethon message to a RawItem, or None if it has no text."""
    body = (
        getattr(msg, "message", None)
        or getattr(msg, "text", None)
        or getattr(msg, "caption", None)
        or ""
    ).strip()
    if not body:
        return None
    mid = getattr(msg, "id", None) or getattr(msg, "message_id", None)
    short = _short_id(channel_id)
    return RawItem(
        source_type=SourceType.CHANNEL,
        source_ref=str(channel_id),
        external_id=str(mid),
        content_type=ContentType.ARTICLE,
        title=body.splitlines()[0][:120],
        url=f"https://t.me/c/{short}/{mid}",
        body_text=body,
        published_at=getattr(msg, "date", None),
    )


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------


def _is_pdf(msg: Any) -> bool:
    doc = getattr(getattr(msg, "media", None), "document", None)
    return getattr(doc, "mime_type", "") == "application/pdf"


def _pdf_filename(msg: Any) -> str:
    doc = getattr(getattr(msg, "media", None), "document", None)
    if doc is None:
        return ""
    for attr in getattr(doc, "attributes", []) or []:
        if hasattr(attr, "file_name"):
            return attr.file_name
    return ""


def _file_size_mb(msg: Any) -> float:
    doc = getattr(getattr(msg, "media", None), "document", None)
    return (doc.size or 0) / 1024 / 1024 if doc else 0.0


def _has_document(msg: Any) -> bool:
    """True if the message carries any file attachment (PDF, EPUB, FB2, …)."""
    return getattr(getattr(msg, "media", None), "document", None) is not None


def _doc_mime(msg: Any) -> str:
    doc = getattr(getattr(msg, "media", None), "document", None)
    return getattr(doc, "mime_type", "") if doc else ""


def _pdf_to_rawitem(
    article: Any,  # pdf_parser.Article
    channel_id: int,
    msg_id: int,
) -> RawItem:
    short = _short_id(channel_id)
    return RawItem(
        source_type=SourceType.CHANNEL,
        source_ref=str(channel_id),
        external_id=f"{msg_id}_p{article.page_start}",
        content_type=ContentType.ARTICLE,
        title=article.title[:120],
        url=f"https://t.me/c/{short}/{msg_id}",
        body_text=article.body_text,
    )


async def _handle_pdf(
    client: Any,
    msg: Any,
    channel_id: int,
    settings: Settings,
    llm: Any,
) -> list[RawItem]:
    from tutor.ingest.pdf_parser import parse_pdf

    if _file_size_mb(msg) > settings.pdf_max_size_mb:
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "article.pdf"
        await client.download_media(msg, file=str(path))
        if not path.exists() or path.stat().st_size == 0:
            return []

        articles = await parse_pdf(path, llm, max_articles=settings.pdf_articles_per_issue)
        return [_pdf_to_rawitem(a, channel_id, msg.id) for a in articles]


# ---------------------------------------------------------------------------
# EPUB helpers
# ---------------------------------------------------------------------------

_EPUB_MIME = "application/epub+zip"
_EPUB_SKIP_NAMES = ("toc", "nav", "cover", "title", "copyright", "colophon")


def _is_epub(msg: Any) -> bool:
    doc = getattr(getattr(msg, "media", None), "document", None)
    return getattr(doc, "mime_type", "") == _EPUB_MIME


def _epub_text(raw_html: bytes) -> str:
    """Strip HTML tags and normalise whitespace from an EPUB content file."""
    decoded = raw_html.decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", decoded)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _epub_title(raw_html: bytes, fallback: str) -> str:
    decoded = raw_html.decode("utf-8", errors="ignore")
    m = re.search(r"<h[1-3][^>]*>(.*?)</h[1-3]>", decoded, re.DOTALL | re.IGNORECASE)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        return html_lib.unescape(title)[:120] or fallback
    return fallback


async def _handle_epub(
    client: Any,
    msg: Any,
    channel_id: int,
    settings: Settings,
) -> list[RawItem]:
    if _file_size_mb(msg) > settings.pdf_max_size_mb:
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "book.epub"
        await client.download_media(msg, file=str(path))
        if not path.exists() or path.stat().st_size == 0:
            return []

        items: list[RawItem] = []
        short = _short_id(channel_id)
        try:
            with zipfile.ZipFile(path) as zf:
                content_files = sorted(
                    n
                    for n in zf.namelist()
                    if n.lower().endswith((".xhtml", ".html", ".htm"))
                    and not any(skip in n.lower() for skip in _EPUB_SKIP_NAMES)
                )
                for i, fname in enumerate(content_files[: settings.pdf_articles_per_issue]):
                    raw_html = zf.read(fname)
                    text = _epub_text(raw_html)
                    if len(text) < settings.min_article_len:
                        continue
                    title = _epub_title(raw_html, fallback=fname.rsplit("/", 1)[-1])
                    items.append(
                        RawItem(
                            source_type=SourceType.CHANNEL,
                            source_ref=str(channel_id),
                            external_id=f"{msg.id}_epub_{i}",
                            content_type=ContentType.ARTICLE,
                            title=title,
                            url=f"https://t.me/c/{short}/{msg.id}",
                            body_text=text,
                        )
                    )
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError):
            pass

        return items


# ---------------------------------------------------------------------------
# FB2 helpers (FictionBook is a single XML file — stdlib only, no deps)
# ---------------------------------------------------------------------------

_FB2_MIME = "application/x-fictionbook+xml"


def _is_fb2(msg: Any) -> bool:
    if _doc_mime(msg) == _FB2_MIME:
        return True
    return _has_document(msg) and _pdf_filename(msg).lower().endswith(".fb2")


def _fb2_local(tag: str) -> str:
    """Strip an XML namespace from a tag name (``{ns}body`` -> ``body``)."""
    return tag.rsplit("}", 1)[-1]


def _fb2_sections(raw_xml: bytes) -> list[tuple[str, str]]:
    """Return (title, text) for each top-level <section> of the main FB2 body.

    Only the first <body> is used (later bodies hold footnotes/endnotes).
    """
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return []

    sections: list[tuple[str, str]] = []
    for body in (el for el in root.iter() if _fb2_local(el.tag) == "body"):
        for section in (c for c in body if _fb2_local(c.tag) == "section"):
            title = ""
            title_el = next((c for c in section if _fb2_local(c.tag) == "title"), None)
            if title_el is not None:
                title = " ".join(t.strip() for t in title_el.itertext() if t.strip())
            text = re.sub(
                r"\s+", " ", " ".join(t.strip() for t in section.itertext() if t.strip())
            ).strip()
            sections.append((title[:120], text))
        break  # main body only
    return sections


async def _handle_fb2(
    client: Any,
    msg: Any,
    channel_id: int,
    settings: Settings,
) -> list[RawItem]:
    if _file_size_mb(msg) > settings.pdf_max_size_mb:
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "book.fb2"
        await client.download_media(msg, file=str(path))
        if not path.exists() or path.stat().st_size == 0:
            return []

        items: list[RawItem] = []
        short = _short_id(channel_id)
        for i, (title, text) in enumerate(
            _fb2_sections(path.read_bytes())[: settings.pdf_articles_per_issue]
        ):
            if len(text) < settings.min_article_len:
                continue
            items.append(
                RawItem(
                    source_type=SourceType.CHANNEL,
                    source_ref=str(channel_id),
                    external_id=f"{msg.id}_fb2_{i}",
                    content_type=ContentType.ARTICLE,
                    title=title or f"Section {i + 1}",
                    url=f"https://t.me/c/{short}/{msg.id}",
                    body_text=text,
                )
            )
        return items


# ---------------------------------------------------------------------------
# Channel scraping with watermarks
# ---------------------------------------------------------------------------


def _is_text_only(msg: Any) -> bool:
    """True if the message has text but no file attachment (an announcement/post)."""
    if _has_document(msg):
        return False
    body = (
        getattr(msg, "message", None)
        or getattr(msg, "text", None)
        or getattr(msg, "caption", None)
        or ""
    ).strip()
    return bool(body)


def _announcement_ids(by_id: dict[int, Any]) -> set[int]:
    """Ids of text-only messages that merely announce an adjacent file.

    Book/magazine channels post a short description (msg N) followed by the
    actual file (msg N+1). Those descriptions are not real articles, so we drop
    them. Channel message ids are sequential, so the announcement sits at N-1
    (preferred) or N+1 relative to the file.
    """
    consumed: set[int] = set()
    for mid, msg in by_id.items():
        if not _has_document(msg):
            continue
        for adj in (mid - 1, mid + 1):
            adj_msg = by_id.get(adj)
            if adj_msg is not None and adj not in consumed and _is_text_only(adj_msg):
                consumed.add(adj)
                break
    return consumed


async def scrape_channel(
    client: Any,
    channel_id: int,
    settings: Settings,
    repo: Repository,
    llm: Any = None,
) -> list[RawItem]:
    """Scrape one channel using a two-phase watermark strategy, then pair
    announcement posts with their files so blurbs are never stored as articles.

    Watermark phases (collect):
      Phase 1 — new messages since the last run (id > max_scraped_id).
      Phase 2 — historical backfill going backwards from the oldest seen id.
      First run — the most recent `scrape_history_batch` messages.

    Parse pass:
      Documents (PDF/EPUB/FB2) are downloaded and parsed into real articles; the
      adjacent announcement text is consumed (skipped). Unsupported file formats
      are logged and skipped, but their announcement is still consumed so no fake
      "~1 min read" blurb is left behind. Genuinely standalone text posts (no
      adjacent file) keep the normal `normalize` + `is_suitable` behavior.
    """
    channel_ref = str(channel_id)
    marked = _marked_id(channel_id)
    wm = repo.get_watermark(channel_ref)

    # --- Collect messages into a map so we can look at neighbors. ---
    by_id: dict[int, Any] = {}

    async def _collect(msg: Any) -> None:
        mid = getattr(msg, "id", None)
        if mid is not None:
            by_id[int(mid)] = msg

    if wm is None:
        async for msg in client.iter_messages(marked, limit=settings.scrape_history_batch):
            await _collect(msg)
    else:
        async for msg in client.iter_messages(
            marked, min_id=int(wm["max_scraped_id"]), limit=settings.scrape_daily_limit
        ):
            await _collect(msg)
        min_seen = wm["min_scraped_id"]
        if min_seen is not None:
            async for msg in client.iter_messages(
                marked, offset_id=int(min_seen), limit=settings.scrape_history_batch
            ):
                await _collect(msg)

    # --- Pair announcements with files, then parse. ---
    announcements = _announcement_ids(by_id)
    items: list[RawItem] = []
    for mid in sorted(by_id):
        msg = by_id[mid]
        if _has_document(msg):
            if _is_pdf(msg) and llm is not None:
                items.extend(await _handle_pdf(client, msg, channel_id, settings, llm))
            elif _is_epub(msg):
                items.extend(await _handle_epub(client, msg, channel_id, settings))
            elif _is_fb2(msg):
                items.extend(await _handle_fb2(client, msg, channel_id, settings))
            else:
                repo.log_job("scrape_skip", "ok", f"{_doc_mime(msg) or 'unknown'} msg {mid}")
        elif mid in announcements:
            continue  # announcement blurb — its file carries the real content
        else:
            raw = normalize(msg, channel_id)
            if raw and is_suitable(
                raw, min_len=settings.min_article_len, max_len=settings.max_article_len
            ):
                items.append(raw)

    # Persist watermarks so the next run knows where we are.
    if by_id:
        repo.set_watermark(channel_ref, max(by_id), min(by_id))

    return items


# ---------------------------------------------------------------------------
# Client construction and top-level entry point
# ---------------------------------------------------------------------------


def _build_client(settings: Settings) -> Any:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if settings.tg_session_string:
        session: Any = StringSession(settings.tg_session_string)
    else:
        session = settings.tg_session_path  # Telethon appends ".session"
    return TelegramClient(session, settings.tg_api_id, settings.tg_api_hash)


async def run_scrape(
    settings: Settings,
    repo: Repository,
    llm: Any = None,
) -> dict[int, int]:
    """Scrape all configured channels into the repository.

    Returns per-channel counts of newly stored (non-duplicate) items.
    Uses watermark-based two-phase scraping so historical content is gradually
    backfilled across daily runs without re-processing already-stored messages.
    """
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise RuntimeError("TG_API_ID and TG_API_HASH are required for scraping (see .env).")
    try:
        client = _build_client(settings)
    except ImportError as exc:
        raise RuntimeError("Install the scraper extra first: `uv sync --extra scrape`.") from exc

    counts: dict[int, int] = {}
    async with client:
        try:
            await client.get_dialogs()
        except Exception:  # noqa: BLE001
            pass
        for channel in settings.channel_ids:
            stored = 0
            for raw in await scrape_channel(client, channel, settings, repo, llm=llm):
                if repo.add_content(raw, settings.admin_user_id) is not None:
                    stored += 1
            counts[channel] = stored
    return counts
