"""Scheduled jobs. They prepare content and nudge the learner; the interactive
quiz itself is still driven by the bot's inline keyboards."""

from __future__ import annotations

from tutor.bot.keyboards import quiz_invite
from tutor.domain.enums import DeliveryStatus, QuizKind
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


async def morning_push(svc: Services, user_id: int, limit: int = 3) -> list[int]:
    """Deliver NEW items to the learner with a 'Quiz me' button."""
    delivered = await deliver_new(svc, user_id, limit)
    svc.repo.log_job("morning_push", "ok", f"delivered {len(delivered)}")
    return delivered


async def evening_eval(svc: Services, user_id: int) -> list[int]:
    """For each DELIVERED item, ensure a quiz exists and nudge the learner."""
    prepared: list[int] = []
    for item in svc.repo.fetch_by_status(user_id, DeliveryStatus.DELIVERED):
        if svc.repo.get_quiz(item.id, QuizKind.READING) is None:
            await build_evaluation(svc, item.id, user_id)
        title = item.title or "today's reading"
        await svc.notifier.send(
            user_id, f"🌙 Evening quiz is ready: <b>{title}</b>", keyboard=quiz_invite(item.id)
        )
        prepared.append(item.id)
    svc.repo.log_job("evening_eval", "ok", f"prepared {len(prepared)}")
    return prepared
