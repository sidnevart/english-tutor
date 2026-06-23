"""Daily article ingestion from The Guardian Open Platform API.

Fetches recent articles from world, science, and technology sections,
filters to TOEFL-scale length, and stores them as ContentType.ARTICLE.
Requires a Guardian API key — the 'test' key works for development;
register for a free key at open-platform.theguardian.com.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from tutor.config import Settings
from tutor.db.repository import Repository
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem

_GUARDIAN_API = "https://content.guardianapis.com/search"
_SECTIONS = ["world", "science", "technology", "environment"]


async def run_article_ingest(
    settings: Settings, repo: Repository, articles_per_section: int = 2
) -> dict[str, int]:
    """Fetch recent articles from Guardian API and store new ones.

    Returns per-section counts of newly stored articles.
    Skips silently if `guardian_api_key` is blank.
    """
    if not settings.guardian_api_key:
        return {}

    counts: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for section in _SECTIONS:
            stored = 0
            try:
                resp = await client.get(
                    _GUARDIAN_API,
                    params={
                        "api-key": settings.guardian_api_key,
                        "show-fields": "bodyText",
                        "page-size": articles_per_section * 4,
                        "section": section,
                        "type": "article",
                        "order-by": "newest",
                    },
                )
                resp.raise_for_status()
                results = resp.json().get("response", {}).get("results", [])
                for item in results:
                    body = (item.get("fields") or {}).get("bodyText", "").strip()
                    if not (settings.min_article_len <= len(body) <= settings.max_article_len):
                        continue
                    published_at: datetime | None = None
                    pub_date = item.get("webPublicationDate", "")
                    if pub_date:
                        try:
                            published_at = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    raw = RawItem(
                        source_type=SourceType.RSS,
                        source_ref=f"Guardian/{section}",
                        external_id=item["id"],
                        content_type=ContentType.ARTICLE,
                        title=item.get("webTitle", "")[:120],
                        url=item.get("webUrl", ""),
                        body_text=body,
                        published_at=published_at,
                    )
                    if repo.add_content(raw, settings.admin_user_id) is not None:
                        stored += 1
                        if stored >= articles_per_section:
                            break
            except Exception:  # noqa: BLE001
                pass
            counts[section] = stored
    return counts
