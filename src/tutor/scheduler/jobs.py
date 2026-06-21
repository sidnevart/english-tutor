"""Scheduled jobs: refresh content, push the morning mix, remind about Anki.

The interactive comprehension quiz stays on-demand (the "Quiz me" button); the
Anki words+idioms deck is generated at delivery time, so the evening job is just
a reminder to review.
"""

from __future__ import annotations

from tutor.bot.keyboards import evening_actions
from tutor.domain.enums import ContentType, DeliveryStatus
from tutor.factory import Services
from tutor.pipeline import deliver_new


async def refresh_content(svc: Services) -> dict[str, object]:
    """Fetch fresh content: scrape channels + ingest podcasts. Each source is
    isolated so a failure in one does not block the other or the morning push."""
    from tutor.ingest.rss import run_ingest
    from tutor.ingest.telegram_scraper import run_scrape

    result: dict[str, object] = {}
    try:
        result["channels"] = await run_scrape(svc.settings, svc.repo)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("scrape", "error", str(exc)[:200])
        result["channels"] = {}
    try:
        result["podcasts"] = await run_ingest(svc.settings, svc.repo)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("ingest", "error", str(exc)[:200])
        result["podcasts"] = {}
    svc.repo.log_job("refresh_content", "ok", str(result)[:200])
    return result


async def morning_push(svc: Services, user_id: int) -> list[int]:
    """Deliver a cadence-respecting mix: N articles + M podcasts (per .env), each
    with its words+idioms Anki deck. Podcasts are never crowded out by articles."""
    delivered: list[int] = []
    delivered += await deliver_new(svc, user_id, svc.settings.morning_articles, ContentType.ARTICLE)
    delivered += await deliver_new(svc, user_id, svc.settings.morning_podcasts, ContentType.PODCAST)
    svc.repo.log_job("morning_push", "ok", f"delivered {len(delivered)}")
    return delivered


async def evening_reminder(svc: Services, user_id: int) -> None:
    """Evening nudge: review Anki + offer a dialog/speaking session."""
    delivered = svc.repo.fetch_by_status(user_id, DeliveryStatus.DELIVERED, limit=50)
    cards = svc.repo.anki_card_count(user_id)
    top = delivered[-1].id if delivered else None  # most recent delivered item
    await svc.notifier.send(
        user_id,
        "🌙 <b>Evening review</b>\n"
        f"• {cards} Anki card(s) waiting — review them in the Anki app 📚\n"
        f"• {len(delivered)} item(s) from today — discuss them or just practice speaking",
        keyboard=evening_actions(top),
    )
    svc.repo.log_job("evening_reminder", "ok", f"delivered={len(delivered)} cards={cards}")
