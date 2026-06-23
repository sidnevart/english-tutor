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
# Channel scraping with watermarks
# ---------------------------------------------------------------------------


async def scrape_channel(
    client: Any,
    channel_id: int,
    settings: Settings,
    repo: Repository,
    llm: Any = None,
) -> list[RawItem]:
    """Scrape one channel using a two-phase watermark strategy.

    Phase 1 — new messages since the last run (id > max_scraped_id).
    Phase 2 — historical backfill: `scrape_history_batch` messages going
               backwards from the oldest message ever seen (id < min_scraped_id).

    First run: fetches the most recent `scrape_history_batch` messages and
    sets both watermarks from the result (no separate phase 2 needed).
    """
    channel_ref = str(channel_id)
    marked = _marked_id(channel_id)
    wm = repo.get_watermark(channel_ref)

    items: list[RawItem] = []
    msg_ids: list[int] = []

    async def _process(msg: Any) -> None:
        mid = getattr(msg, "id", None)
        if mid is not None:
            msg_ids.append(int(mid))
        if _is_pdf(msg) and llm is not None:
            items.extend(await _handle_pdf(client, msg, channel_id, settings, llm))
        elif _is_epub(msg):
            items.extend(await _handle_epub(client, msg, channel_id, settings))
        else:
            raw = normalize(msg, channel_id)
            if raw and is_suitable(
                raw,
                min_len=settings.min_article_len,
                max_len=settings.max_article_len,
            ):
                items.append(raw)

    if wm is None:
        # First run — grab the most recent `scrape_history_batch` messages.
        async for msg in client.iter_messages(marked, limit=settings.scrape_history_batch):
            await _process(msg)
    else:
        # Phase 1: new messages since last run (Telethon min_id is exclusive).
        async for msg in client.iter_messages(
            marked, min_id=int(wm["max_scraped_id"]), limit=settings.scrape_daily_limit
        ):
            await _process(msg)

        # Phase 2: historical backfill going backwards from the oldest known message.
        min_seen = wm["min_scraped_id"]
        if min_seen is not None:
            async for msg in client.iter_messages(
                marked,
                offset_id=int(min_seen),
                limit=settings.scrape_history_batch,
            ):
                await _process(msg)

    # Persist watermarks so the next run knows where we are.
    if msg_ids:
        repo.set_watermark(channel_ref, max(msg_ids), min(msg_ids))

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
