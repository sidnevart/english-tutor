"""Telegram channel scraping via a Telethon userbot.

The existing bot_data session is a Telethon session, so we reuse it directly.
The pure `normalize` (message -> RawItem) is unit-tested; the Telethon client
IO is isolated in `run_scrape`, which needs TG_API_ID/TG_API_HASH and the
`scrape` extra installed.

PDF handling: when a message contains a PDF attachment, the scraper downloads
it, extracts articles using pdf_parser, and stores each article as a separate
content_item.
"""

from __future__ import annotations

import tempfile
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


def _is_pdf(msg: Any) -> bool:
    """Check if a message contains a PDF document."""
    media = getattr(msg, "media", None)
    if media is None:
        return False
    doc = getattr(media, "document", None)
    if doc is None:
        return False
    return getattr(doc, "mime_type", "") == "application/pdf"


def _pdf_filename(msg: Any) -> str:
    """Extract filename from a PDF message."""
    doc = getattr(msg.media, "document", None)
    if doc is None:
        return ""
    for attr in getattr(doc, "attributes", []) or []:
        if hasattr(attr, "file_name"):
            return attr.file_name
    return ""


def _pdf_size_mb(msg: Any) -> float:
    """Get PDF file size in MB."""
    doc = getattr(msg.media, "document", None)
    if doc is None:
        return 0
    return (doc.size or 0) / 1024 / 1024


def _pdf_to_rawitem(
    article: Any,  # pdf_parser.Article
    channel_id: int,
    msg_id: int,
) -> RawItem:
    """Convert a parsed PDF article to a RawItem."""
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
    """Download a PDF, parse it into articles, return as RawItems."""
    from tutor.ingest.pdf_parser import parse_pdf

    size_mb = _pdf_size_mb(msg)
    if size_mb > settings.pdf_max_size_mb:
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "article.pdf"
        await client.download_media(msg, file=str(path))
        if not path.exists() or path.stat().st_size == 0:
            return []

        articles = await parse_pdf(path, llm, max_articles=settings.pdf_articles_per_issue)
        return [_pdf_to_rawitem(a, channel_id, msg.id) for a in articles]


async def scrape_channel(
    client: Any,
    channel_id: int,
    limit: int = 20,
    min_len: int = 350,
    max_len: int = 4500,
    llm: Any = None,
) -> list[RawItem]:
    items: list[RawItem] = []
    async for msg in client.iter_messages(_marked_id(channel_id), limit=limit):
        if _is_pdf(msg) and llm is not None:
            pdf_items = await _handle_pdf(client, msg, channel_id, Settings(), llm)
            items.extend(pdf_items)
        else:
            raw = normalize(msg, channel_id)
            if raw and is_suitable(raw, min_len=min_len, max_len=max_len):
                items.append(raw)
    return items


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
    limit: int = 20,
    llm: Any = None,
) -> dict[int, int]:
    """Scrape all configured channels into the repository. Returns per-channel
    counts of newly stored (non-duplicate) items.

    If llm is provided, PDF attachments are parsed into individual articles.
    """
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise RuntimeError("TG_API_ID and TG_API_HASH are required for scraping (see .env).")
    try:
        client = _build_client(settings)
    except ImportError as exc:
        raise RuntimeError("Install the scraper extra first: `uv sync --extra scrape`.") from exc

    counts: dict[int, int] = {}
    async with client:
        # Refresh the entity cache so channel ids resolve reliably.
        try:
            await client.get_dialogs()
        except Exception:  # noqa: BLE001
            pass
        for channel in settings.channel_ids:
            stored = 0
            for raw in await scrape_channel(
                client,
                channel,
                limit,
                settings.min_article_len,
                settings.max_article_len,
                llm=llm,
            ):
                if repo.add_content(raw, settings.admin_user_id) is not None:
                    stored += 1
            counts[channel] = stored
    return counts
