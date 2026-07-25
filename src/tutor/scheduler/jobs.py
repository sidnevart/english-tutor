"""Scheduled jobs for the error-diary loop.

  Mon/Wed/Fri ~19:23 — push_practice: the bot opens a speaking or writing
                     session (alternating) so the learner practises and errors
                     get captured into session_error.
  Sunday ~10:47     — weekly_summary: error trend + recurring errors + study tips.

The bot embeds the scheduler (`run_bot`), so `push_practice` shares the polling
bot's FSM storage: entering `ConversationState.active` here means the learner's
reply is handled by the normal in-session handlers.
"""

from __future__ import annotations

from typing import Any

from tutor.factory import Services


async def push_practice(svc: Services, user_id: int, bot: Any, storage: Any) -> None:
    """Start a practice session on schedule (alternates speak ↔ write).

    Enters `ConversationState.active` via the shared FSM storage so the
    learner's reply flows into the normal capture path. Skips (and nudges) if a
    session is already open.
    """
    try:
        from aiogram.fsm.context import FSMContext
        from aiogram.fsm.storage.base import StorageKey

        from tutor.bot.conversation import ConversationState, start_practice

        bot_id = bot.id if bot is not None else 0
        key = StorageKey(bot_id=bot_id, chat_id=user_id, user_id=user_id)
        state = FSMContext(storage=storage, key=key)

        current = await state.get_state()
        if current == ConversationState.active:
            await svc.notifier.send(
                user_id,
                "👋 You still have an open practice — reply or /stop to finish it first.",
            )
            svc.repo.log_job("push_practice", "skipped", "session active")
            return

        kind = str(svc.repo.get_pref(user_id, "next_practice", "speak") or "speak")
        if kind not in ("speak", "write"):
            kind = "speak"
        await start_practice(svc, bot, user_id, state, kind)
        svc.repo.set_pref(user_id, "next_practice", "write" if kind == "speak" else "speak")
        svc.repo.log_job("push_practice", "ok", kind)
    except Exception as exc:  # noqa: BLE001 — a job failure must never crash the scheduler
        svc.repo.log_job("push_practice", "error", str(exc)[:200])


async def weekly_summary(svc: Services, user_id: int) -> None:
    """Weekly error-trend summary: streak, error trend, recurring errors, tips."""
    try:
        streak = svc.repo.practice_streak(user_id)
        top_errors = svc.repo.top_session_errors(user_id, limit=5)
        diary = svc.repo.error_diary(user_id)
        distinct = len(diary)
        total = sum(int(r["count"]) for r in diary)

        parts = [
            "📊 <b>Weekly summary</b>\n",
            f"🔥 Streak: <b>{streak} day(s)</b>",
            f"• <b>{total}</b> errors captured across <b>{distinct}</b> distinct mistakes",
        ]

        errors_by_week = svc.repo.error_count_by_week(user_id, weeks=4)
        if errors_by_week:
            trend = ""
            if len(errors_by_week) >= 2:
                diff = errors_by_week[-1]["count"] - errors_by_week[-2]["count"]
                trend = " ↑" if diff > 0 else (" ↓" if diff < 0 else " →")
            week_strs = [f"{r['week']} {r['count']}" for r in errors_by_week]
            parts.append("\n<b>⚠️ Errors per week:</b>" + trend)
            parts.append("  " + " · ".join(week_strs))

        if top_errors:
            parts.append("\n<b>🔄 Top recurring errors:</b>")
            for e in top_errors:
                parts.append(f'  • "{e["error_text"]}" → "{e["correction"]}" ({e["count"]}x)')

        # LLM study tips keyed on the learner's error patterns.
        try:
            from tutor.memory.context import build_learner_context

            ctx = build_learner_context(svc.repo, user_id, svc.settings.soul_dir)
            rec = await svc.llm.complete(
                "You are an English practice coach. Based on this learner's error "
                "patterns, give exactly 2 specific, actionable study tips for the week "
                "ahead, each targeting a recurring mistake class. One sentence each. "
                "Plain text, one per line.",
                f"LEARNER PROFILE:\n{ctx}",
            )
            parts.append(f"\n<b>💡 Study tips:</b>\n{rec.strip()}")
        except Exception:  # noqa: BLE001
            parts.append(
                "\n<b>💡 Study tips:</b>\n  • Run /speak or /write daily and review /diary."
            )

        parts.append("\n📥 /diary exports your full error log (md / csv / Anki).")
        await svc.notifier.send(user_id, "\n".join(parts))
        svc.repo.log_job(
            "weekly_summary", "ok", f"streak={streak} distinct={distinct} total={total}"
        )
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("weekly_summary", "error", str(exc)[:200])
