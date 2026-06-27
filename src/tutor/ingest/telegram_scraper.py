"""Telegram channel scraping via a Telethon userbot.

The existing bot_data session is a Telethon session, so we reuse it directly.
The pure `normalize` (message -> RawItem) is unit-tested; the Telethon client
IO is isolated in `run_scrape`, which needs TG_API_ID/TG_API_HASH and the
`scrape` extra installed.

Only mid-length, predominantly-English TEXT posts are stored as articles.
File attachments (PDF/EPUB/FB2/…) are logged and skipped — they are not
TOEFL-scale reading material and previously produced oversized "articles".
Book/magazine channels post a short announcement blurb next to the file;
those blurbs are paired with their file and skipped so no fake "~1 min read"
post is left behind.

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
# File-attachment detection (for logging + announcement pairing)
# ---------------------------------------------------------------------------


def _has_document(msg: Any) -> bool:
    """True if the message carries any file attachment (PDF, EPUB, FB2, …)."""
    return getattr(getattr(msg, "media", None), "document", None) is not None


def _doc_mime(msg: Any) -> str:
    doc = getattr(getattr(msg, "media", None), "document", None)
    return getattr(doc, "mime_type", "") if doc else ""


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
    """Scrape one channel using a two-phase watermark strategy, then pair
    announcement posts with their files so blurbs are never stored as articles.

    Watermark phases (collect):
      Phase 1 — new messages since the last run (id > max_scraped_id).
      Phase 2 — historical backfill going backwards from the oldest seen id.
      First run — the most recent `scrape_history_batch` messages.

    Parse pass:
      Only text posts are candidates: `normalize` + `is_suitable`. File
      attachments are logged and skipped (not TOEFL-scale material); their
      adjacent announcement text is consumed so no fake "~1 min read" blurb is
      left behind.
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

    # --- Pair announcements with files, then keep only suitable text posts. ---
    announcements = _announcement_ids(by_id)
    items: list[RawItem] = []
    for mid in sorted(by_id):
        msg = by_id[mid]
        if _has_document(msg):
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
