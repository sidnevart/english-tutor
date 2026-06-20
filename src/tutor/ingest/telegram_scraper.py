"""Telegram channel scraping via a Pyrogram (kurigram) userbot.

The pure `normalize` (message -> RawItem) is unit-tested; the Pyrogram client
IO is isolated in `run_scrape`, which needs TG_API_ID/TG_API_HASH and the
`scrape` extra installed.
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


def normalize(msg: Any, channel_id: int) -> RawItem | None:
    """Convert a Pyrogram message to a RawItem, or None if it has no text."""
    body = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
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


async def scrape_channel(client: Any, channel_id: int, limit: int = 20) -> list[RawItem]:
    items: list[RawItem] = []
    async for msg in client.get_chat_history(channel_id, limit=limit):
        raw = normalize(msg, channel_id)
        if raw:
            items.append(raw)
    return items


async def run_scrape(settings: Settings, repo: Repository, limit: int = 20) -> dict[int, int]:
    """Scrape all configured channels into the repository. Returns per-channel
    counts of newly stored (non-duplicate) items."""
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise RuntimeError("TG_API_ID and TG_API_HASH are required for scraping (see .env).")
    try:
        from pyrogram import Client
    except ImportError as exc:
        raise RuntimeError("Install the scraper extra first: `uv sync --extra scrape`.") from exc

    kwargs: dict[str, Any] = {"api_id": settings.tg_api_id, "api_hash": settings.tg_api_hash}
    if settings.tg_session_string:
        kwargs["name"] = "tutor_scraper"
        kwargs["session_string"] = settings.tg_session_string
    else:
        from pathlib import Path

        session = Path(settings.tg_session_path)
        kwargs["name"] = session.name
        kwargs["workdir"] = str(session.parent or ".")

    counts: dict[int, int] = {}
    async with Client(**kwargs) as client:
        for channel in settings.channel_ids:
            stored = 0
            for raw in await scrape_channel(client, channel, limit):
                if repo.add_content(raw, settings.admin_user_id) is not None:
                    stored += 1
            counts[channel] = stored
    return counts
