"""Scheduled jobs. They prepare content and nudge the learner; the interactive
quiz itself is still driven by the bot's inline keyboards."""

from __future__ import annotations

from tutor.bot.keyboards import quiz_invite
from tutor.domain.enums import ContentType, DeliveryStatus, QuizKind
from tutor.factory import Services
from tutor.pipeline import build_evaluation, deliver_new


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
    """Deliver a cadence-respecting mix: N articles + M podcasts (per .env), so
    podcasts are never crowded out by articles."""
    delivered: list[int] = []
    delivered += await deliver_new(svc, user_id, svc.settings.morning_articles, ContentType.ARTICLE)
    delivered += await deliver_new(svc, user_id, svc.settings.morning_podcasts, ContentType.PODCAST)
    svc.repo.log_job("morning_push", "ok", f"delivered {len(delivered)}")
    return delivered


async def evening_eval(svc: Services, user_id: int) -> list[int]:
    """For each DELIVERED item, ensure a quiz exists and nudge the learner."""
    prepared: list[int] = []
    for item in svc.repo.fetch_by_status(user_id, DeliveryStatus.DELIVERED):
        if svc.repo.get_quiz(item.id, QuizKind.READING) is None:
            await build_evaluation(svc, item.id, user_id)
        title = item.title or "today's material"
        label = "🎧 Listening quiz" if item.content_type == ContentType.PODCAST else "📖 Quiz me"
        await svc.notifier.send(
            user_id,
            f"🌙 Evening quiz is ready: <b>{title}</b>",
            keyboard=quiz_invite(item.id, label),
        )
        prepared.append(item.id)
    svc.repo.log_job("evening_eval", "ok", f"prepared {len(prepared)}")
    return prepared
