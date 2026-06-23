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
    """Fetch fresh content: scrape channels + ingest podcasts. Each source is
    isolated so a failure in one does not block the other or the morning push."""
    from tutor.ingest.rss import run_ingest
    from tutor.ingest.telegram_scraper import run_scrape

    result: dict[str, object] = {}
    try:
        result["channels"] = await run_scrape(svc.settings, svc.repo, llm=svc.llm)
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
    try:
        delivered: list[int] = []
        delivered += await deliver_new(
            svc, user_id, svc.settings.morning_articles, ContentType.ARTICLE
        )
        delivered += await deliver_new(
            svc, user_id, svc.settings.morning_podcasts, ContentType.PODCAST
        )
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


async def evening_worksheet(svc: Services, user_id: int) -> None:
    """Generate and send an evening worksheet with TOEFL-format exercises.

    Collects today's vocabulary, speaking errors, and article content,
    then generates a printable exercise sheet (MD + PDF).
    """
    from pathlib import Path

    from tutor.worksheet.generator import generate_worksheet, worksheet_to_json
    from tutor.worksheet.renderer import render_worksheet_md, render_worksheet_pdf

    try:
        # Collect today's data.
        vocab = svc.repo.get_vocab_today(user_id, limit=15)
        errors = svc.repo.recent_session_errors(user_id, limit=5)
        articles = svc.repo.get_today_articles(user_id, limit=2)

        if not vocab and not articles:
            await svc.notifier.send(
                user_id,
                "📝 No materials today to generate a worksheet. "
                "Read an article or listen to a podcast first!",
            )
            return

        # Generate exercises.
        payload = await generate_worksheet(svc.llm, vocab, errors, articles)

        # Save to DB.
        items_json = worksheet_to_json(payload)
        worksheet_id = svc.repo.save_worksheet(user_id, items_json)

        # Render files.
        from datetime import UTC, datetime

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        md_content = render_worksheet_md(payload, date=date_str)

        md_path = Path(svc.settings.data_dir) / f"worksheet_{date_str}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")

        pdf_path = render_worksheet_pdf(md_content, md_path.with_suffix(".pdf"))

        # Send to user.
        await svc.notifier.send(
            user_id,
            f"📝 <b>Evening Worksheet — {date_str}</b>\n\n"
            f"Today's practice includes:\n"
            f"  • {len(payload.fill_blanks)} fill-in-the-blank questions\n"
            f"  • {len(payload.error_correction)} error corrections\n"
            f"  • {len(payload.sentence_transform)} sentence transformations\n"
            f"  • {sum(len(s.questions) for s in payload.mini_reading)} reading questions\n"
            f"  • {len(payload.collocation_match)} collocation matches\n\n"
            f"Fill in your answers and send the file back when done!",
        )
        await svc.notifier.send_file(user_id, md_path, caption="Markdown version")
        await svc.notifier.send_file(user_id, pdf_path, caption="PDF version")

        svc.repo.log_job(
            "evening_worksheet",
            "ok",
            f"worksheet_id={worksheet_id} vocab={len(vocab)} errors={len(errors)}",
        )
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("evening_worksheet", "error", str(exc)[:200])


async def homework_push(svc: Services, user_id: int) -> None:
    """Generate and send a homework file with all of today's assignments.

    Combines reading comprehension (articles), listening comprehension (podcasts),
    vocabulary exercises, error correction, and more into a single printable file.
    The user fills it in at their own pace and sends it back for grading.
    """
    from pathlib import Path

    from tutor.pipeline import ensure_transcript
    from tutor.worksheet.generator import generate_worksheet, worksheet_to_json
    from tutor.worksheet.renderer import render_worksheet_md, render_worksheet_pdf

    try:
        # Collect today's data.
        vocab = svc.repo.get_vocab_today(user_id, limit=15)
        errors = svc.repo.recent_session_errors(user_id, limit=5)
        articles = svc.repo.get_today_articles(user_id, limit=2)
        podcasts = svc.repo.get_today_podcasts(user_id, limit=2)

        if not vocab and not articles and not podcasts:
            await svc.notifier.send(
                user_id,
                "📝 No materials today for homework. "
                "Wait for the morning push or use /next to get content!",
            )
            return

        # Ensure podcast transcripts are available.
        for pod in podcasts:
            if not pod.body_text.strip():
                try:
                    await ensure_transcript(svc, pod.id)
                except Exception:  # noqa: BLE001
                    pass  # Skip podcasts that fail to transcribe.
        # Re-fetch podcasts with transcripts.
        if podcasts:
            podcasts = svc.repo.get_today_podcasts(user_id, limit=2)

        # Generate exercises (including reading/listening quizzes).
        payload = await generate_worksheet(svc.llm, vocab, errors, articles, podcasts)

        # Save to DB.
        items_json = worksheet_to_json(payload)
        worksheet_id = svc.repo.save_worksheet(user_id, items_json)

        # Render files.
        from datetime import UTC, datetime

        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        md_content = render_worksheet_md(payload, date=date_str)

        md_path = Path(svc.settings.data_dir) / f"homework_{date_str}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")

        pdf_path = render_worksheet_pdf(md_content, md_path.with_suffix(".pdf"))

        # Count sections for the summary.
        sections: list[str] = []
        if payload.reading_quiz:
            sections.append(f"  • {len(payload.reading_quiz)} reading comprehension questions")
        if payload.listening_quiz:
            sections.append(f"  • {len(payload.listening_quiz)} listening comprehension questions")
        if payload.fill_blanks:
            sections.append(f"  • {len(payload.fill_blanks)} fill-in-the-blank questions")
        if payload.error_correction:
            sections.append(f"  • {len(payload.error_correction)} error corrections")
        if payload.sentence_transform:
            sections.append(f"  • {len(payload.sentence_transform)} sentence transformations")
        if payload.mini_reading:
            sections.append(
                f"  • {sum(len(s.questions) for s in payload.mini_reading)} mini reading questions"
            )
        if payload.collocation_match:
            sections.append(f"  • {len(payload.collocation_match)} collocation matches")

        # Send to user.
        await svc.notifier.send(
            user_id,
            f"📝 <b>Homework — {date_str}</b>\n\n"
            f"Today's assignments:\n"
            + "\n".join(sections)
            + "\n\nFill in your answers and send the .md file back when done!",
        )
        await svc.notifier.send_file(user_id, md_path, caption="Homework (Markdown)")
        await svc.notifier.send_file(user_id, pdf_path, caption="Homework (PDF)")

        svc.repo.log_job(
            "homework_push",
            "ok",
            f"worksheet_id={worksheet_id} articles={len(articles)} podcasts={len(podcasts)}",
        )
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("homework_push", "error", str(exc)[:200])


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
    """Weekly progress summary: stats, weak topics, recurring errors, recommendations."""
    try:
        delivered = svc.repo.count_status(user_id, DeliveryStatus.DELIVERED)
        reviewed = svc.repo.count_status(user_id, DeliveryStatus.REVIEWED)
        cards = svc.repo.anki_card_count(user_id)
        essays = svc.repo.essay_count(user_id)
        streak = svc.repo.practice_streak(user_id)
        weak = svc.repo.weak_topics(user_id, limit=3)
        strong = svc.repo.strong_topics(user_id, limit=3)
        top_errors = svc.repo.top_session_errors(user_id, limit=3)

        parts = [
            "📊 <b>Weekly Summary</b>\n",
            f"🔥 Streak: <b>{streak} day(s)</b>",
            f"• Reviewed this week: <b>{reviewed}</b> items",
            f"• Anki cards total: <b>{cards}</b>",
            f"• Essays written: <b>{essays}</b>",
            f"• Items pending review: <b>{delivered}</b>",
        ]

        if weak:
            parts.append("\n<b>📉 Focus areas (weakest topics):</b>")
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

        parts.append(
            "\n<b>💡 Recommendations:</b>\n"
            "  • Use /review for targeted grammar &amp; vocabulary practice\n"
            "  • Use /write for TOEFL essay practice\n"
            "  • Use /coach for an adaptive learning session"
        )

        await svc.notifier.send(user_id, "\n".join(parts))
        svc.repo.log_job("weekly_summary", "ok", f"streak={streak} reviewed={reviewed}")
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("weekly_summary", "error", str(exc)[:200])
