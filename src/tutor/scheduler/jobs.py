"""Scheduled jobs: content refresh, morning delivery, daytime check-in, evening review.

The learning loop:
  07:00 — refresh content (scrape + ingest)
  07:30 — morning push (articles + podcasts with Anki decks)
  13:00 — daytime check-in (praise completed, nudge incomplete)
  20:00 — evening reminder (Anki cards, unreviewed items, errors → /review)
  Wed+Sat 18:00 — essay reminder
  Sun 19:00 — weekly summary
"""

from __future__ import annotations

from tutor.bot.keyboards import evening_actions
from tutor.domain.enums import ContentType, DeliveryStatus
from tutor.factory import Services
from tutor.pipeline import deliver_new


async def refresh_content(svc: Services) -> dict[str, object]:
    """Fetch fresh content: Guardian articles + RSS podcasts.

    Telegram channel scraping is disabled — TG channels send 60-page PDFs/books
    that aren't TOEFL-scale reading material. The Guardian API (4 sections)
    provides clean, TOEFL-scale articles. Each source is isolated so a failure
    in one does not block the others.
    """
    from tutor.ingest.article_web import run_article_ingest
    from tutor.ingest.rss import run_ingest

    result: dict[str, object] = {}
    try:
        result["podcasts"] = await run_ingest(svc.settings, svc.repo)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("ingest", "error", str(exc)[:200])
        result["podcasts"] = {}
    try:
        result["articles"] = await run_article_ingest(svc.settings, svc.repo)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("article_ingest", "error", str(exc)[:200])
        result["articles"] = {}
    svc.repo.log_job("refresh_content", "ok", str(result)[:200])
    return result


async def morning_push(svc: Services, user_id: int) -> list[int]:
    """Deliver a cadence-respecting mix: N articles + M podcasts (per .env), each
    with its words+idioms Anki deck, then send the single daily TOEFL file
    (Reading passages + Listening audio + Vocabulary) for the learner to fill in."""
    from tutor.worksheet.daily_file import send_daily_file

    try:
        delivered: list[int] = []
        delivered += await deliver_new(
            svc, user_id, svc.settings.morning_articles, ContentType.ARTICLE
        )
        delivered += await deliver_new(
            svc, user_id, svc.settings.morning_podcasts, ContentType.PODCAST
        )
        if delivered:
            await send_daily_file(svc, user_id, delivered)
        svc.repo.log_job("morning_push", "ok", f"delivered {len(delivered)}")
        return delivered
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("morning_push", "error", str(exc)[:200])
        return []


async def daytime_checkin(svc: Services, user_id: int) -> None:
    """Mid-day check-in: praise completed quizzes, nudge incomplete ones.

    Fires ~5h after morning push. Shows:
    - Praise for items already quizzed (articles read, podcasts listened)
    - Nudge for items still awaiting review
    - Streak encouragement
    """
    try:
        reviewed = svc.repo.fetch_by_status(user_id, DeliveryStatus.REVIEWED, limit=10)
        delivered = svc.repo.fetch_by_status(user_id, DeliveryStatus.DELIVERED, limit=10)
        streak = svc.repo.practice_streak(user_id)

        parts: list[str] = []

        # Praise completed items.
        if reviewed:
            # Filter to today's reviewed items.
            from datetime import UTC, datetime

            today = datetime.now(UTC).date()
            today_reviewed = [
                it for it in reviewed if it.reviewed_at and it.reviewed_at.date() == today
            ]
            if today_reviewed:
                parts.append("🎉 <b>Great work today!</b>\n")
                for it in today_reviewed:
                    kind = "🎧 podcast" if it.content_type == ContentType.PODCAST else "📰 article"
                    title = it.title or "Untitled"
                    # Get quiz score.
                    quiz = svc.repo.get_quiz_auto(it.id)
                    score_str = ""
                    if quiz:
                        attempts = svc.repo.attempts_for_content(it.id, user_id)
                        if attempts:
                            correct = sum(1 for a in attempts if a.is_correct)
                            total = len(attempts)
                            pct = round(100 * correct / total) if total else 0
                            emoji = "✅" if pct >= 70 else "📝"
                            score_str = f" — {emoji} {correct}/{total} ({pct}%)"
                    parts.append(f"  ✅ {kind}: <b>{title}</b>{score_str}")

        # Nudge for incomplete items.
        if delivered:
            parts.append(f"\n📋 <b>Still waiting for you ({len(delivered)}):</b>")
            for it in delivered[:3]:
                is_pod = it.content_type == ContentType.PODCAST
                kind = "🎧" if is_pod else "📰"
                title = it.title or "Untitled"
                parts.append(f"  {kind} {title}")
            if len(delivered) > 3:
                parts.append(f"  ... and {len(delivered) - 3} more")

        if not parts:
            # Nothing to report — either all done or nothing delivered yet.
            if streak > 0:
                parts.append(f"🔥 Streak: <b>{streak} day(s)</b> — keep it up!")
            else:
                return  # Nothing to say.

        if streak > 0 and reviewed:
            parts.append(f"\n🔥 Streak: <b>{streak} day(s)</b>")

        await svc.notifier.send(user_id, "\n".join(parts))
        svc.repo.log_job(
            "daytime_checkin", "ok", f"reviewed={len(reviewed)} delivered={len(delivered)}"
        )
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("daytime_checkin", "error", str(exc)[:200])


async def evening_reminder(svc: Services, user_id: int) -> None:
    """Evening reminder: Anki cards, unreviewed content, errors → /review.

    Shows:
    - How many Anki cards are waiting
    - Specific unreviewed items (articles to read, podcasts to listen)
    - Errors from today's sessions → /review
    - Streak
    - Keyboard: discuss + speak + review buttons
    """
    try:
        delivered = svc.repo.fetch_by_status(user_id, DeliveryStatus.DELIVERED, limit=50)
        cards = svc.repo.anki_card_count(user_id)
        streak = svc.repo.practice_streak(user_id)
        errors_today = svc.repo.recent_session_errors(user_id, limit=10)

        parts: list[str] = ["🌙 <b>Evening review</b>\n"]

        # Anki cards.
        if cards > 0:
            parts.append(f"📚 <b>{cards} Anki card(s)</b> waiting — review them in the Anki app")
        else:
            parts.append("📚 No Anki cards yet — complete quizzes to generate cards")

        # Unreviewed items — specific names.
        if delivered:
            parts.append(f"\n📋 <b>Today's materials ({len(delivered)}):</b>")
            for it in delivered:
                kind = "🎧 podcast" if it.content_type == ContentType.PODCAST else "📰 article"
                title = it.title or "Untitled"
                parts.append(f"  • {kind}: {title}")
            parts.append("\nTap the buttons below to start a quiz or discussion!")
        else:
            parts.append("\n✅ All today's materials reviewed — great job!")

        # Errors from today → suggest /review.
        if errors_today:
            parts.append(
                f"\n🔄 <b>{len(errors_today)} error(s)</b> from today's sessions — "
                f"run /review to practice fixing them"
            )

        # Streak.
        if streak > 0:
            parts.append(f"\n🔥 Streak: <b>{streak} day(s)</b>")

        # Keyboard: discuss + speak + review.
        top = delivered[-1].id if delivered else None
        await svc.notifier.send(
            user_id,
            "\n".join(parts),
            keyboard=evening_actions(top),
        )
        svc.repo.log_job("evening_reminder", "ok", f"delivered={len(delivered)} cards={cards}")
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("evening_reminder", "error", str(exc)[:200])


async def essay_reminder(svc: Services, user_id: int) -> None:
    """Weekly nudge to practice TOEFL essay writing."""
    try:
        essay_count = svc.repo.essay_count(user_id)
        last_type = svc.repo.last_essay_type(user_id)
        from tutor.eval.essay import next_essay_type

        next_type = next_essay_type(last_type)
        await svc.notifier.send(
            user_id,
            f"📝 <b>Weekly writing practice</b>\n\n"
            f"You've written {essay_count} essay(s) so far. "
            f"This week's type: <b>{next_type.title()}</b>.\n\n"
            f"Use /write to start your TOEFL essay practice!",
        )
        svc.repo.log_job("essay_reminder", "ok", f"count={essay_count} next_type={next_type}")
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("essay_reminder", "error", str(exc)[:200])


async def weekly_summary(svc: Services, user_id: int) -> None:
    """Weekly progress summary: stats, trends, topics, errors, LLM recommendations."""
    try:
        delivered = svc.repo.count_status(user_id, DeliveryStatus.DELIVERED)
        reviewed = svc.repo.count_status(user_id, DeliveryStatus.REVIEWED)
        cards = svc.repo.anki_card_count(user_id)
        essays = svc.repo.essay_count(user_id)
        streak = svc.repo.practice_streak(user_id)
        vocab_n = svc.repo.vocab_seen_count(user_id)
        weak = svc.repo.weak_topics(user_id, limit=3)
        strong = svc.repo.strong_topics(user_id, limit=3)
        top_errors = svc.repo.top_session_errors(user_id, limit=3)

        parts = [
            "📊 <b>Weekly Summary</b>\n",
            f"🔥 Streak: <b>{streak} day(s)</b>",
            f"• Reviewed: <b>{reviewed}</b>  ·  Pending: <b>{delivered}</b>",
            f"• Anki cards: <b>{cards}</b>  ·  Vocabulary: <b>{vocab_n}</b> words",
            f"• Essays: <b>{essays}</b>",
        ]

        writing = svc.repo.essay_scores(user_id)
        if writing["count"]:
            parts.append(f"• Writing avg: <b>{(writing['avg'] or 0.0):.1f}/5</b>")
        speaking = svc.repo.speaking_scores(user_id)
        if speaking["count"]:
            parts.append(f"• Speaking avg: <b>{(speaking['avg'] or 0.0):.1f}/4</b>")

        # Quiz accuracy trend.
        accuracy = svc.repo.quiz_accuracy_by_week(user_id, weeks=4)
        if accuracy:
            trend = ""
            if len(accuracy) >= 2:
                diff = accuracy[-1]["pct"] - accuracy[-2]["pct"]
                trend = " ↑" if diff > 0 else (" ↓" if diff < 0 else " →")
            week_strs = [f"{r['week']} {round(r['pct'])}%" for r in accuracy]
            parts.append("\n<b>📈 Quiz accuracy:</b>" + trend)
            parts.append("  " + " · ".join(week_strs))

        # Error trend.
        errors_by_week = svc.repo.error_count_by_week(user_id, weeks=4)
        if errors_by_week:
            trend = ""
            if len(errors_by_week) >= 2:
                diff = errors_by_week[-1]["count"] - errors_by_week[-2]["count"]
                trend = " ↑" if diff > 0 else (" ↓" if diff < 0 else " →")
            week_strs = [f"{r['week']} {r['count']}" for r in errors_by_week]
            parts.append("\n<b>⚠️ Errors:</b>" + trend)
            parts.append("  " + " · ".join(week_strs))

        if weak:
            parts.append("\n<b>📉 Focus areas:</b>")
            for t in weak:
                pct = round(t["avg_score"] * 100)
                parts.append(f"  • {t['topic']}: {pct}%")

        if strong:
            parts.append("\n<b>📈 Strongest topics:</b>")
            for t in strong:
                pct = round(t["avg_score"] * 100)
                parts.append(f"  • {t['topic']}: {pct}%")

        if top_errors:
            parts.append("\n<b>🔄 Top recurring errors:</b>")
            for e in top_errors:
                parts.append(f'  • "{e["error_text"]}" → "{e["correction"]}" ({e["count"]}x)')

        # LLM-generated recommendations.
        try:
            from tutor.memory.context import build_learner_context

            ctx = build_learner_context(svc.repo, user_id, svc.settings.soul_dir)
            rec = await svc.llm.complete(
                "You are a TOEFL coach. Based on this learner's profile, give exactly "
                "2 specific, actionable study recommendations for the week ahead. "
                "Keep each to one sentence. Return plain text, one recommendation per line.",
                f"LEARNER PROFILE:\n{ctx}",
            )
            parts.append(f"\n<b>💡 Recommendations:</b>\n{rec.strip()}")
        except Exception:  # noqa: BLE001
            parts.append(
                "\n<b>💡 Recommendations:</b>\n"
                "  • Use /daily + /speaking + /write for balanced daily practice."
            )

        await svc.notifier.send(user_id, "\n".join(parts))
        svc.repo.log_job(
            "weekly_summary", "ok", f"streak={streak} reviewed={reviewed} vocab={vocab_n}"
        )
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("weekly_summary", "error", str(exc)[:200])
