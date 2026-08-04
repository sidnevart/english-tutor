"""Focused Telegram UX for daily TOEFL Reading, Speaking, and Writing."""

from __future__ import annotations

import asyncio
import html
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from tutor.bot.keyboards import reset_confirm
from tutor.bot.views import render_plan, render_prompt
from tutor.eval.email import EmailCheckResult
from tutor.factory import Services
from tutor.practice.engine import ActivePracticeError, Attempt
from tutor.practice.models import Section, TaskType
from tutor.practice.planner import PlanEntry
from tutor.progress.exporter import export_progress, progress_markdown

COMMANDS: list[tuple[str, str]] = [
    ("start", "Register and show today's TOEFL plan"),
    ("today", "Show today's durable plan"),
    ("reading", "Open today's Reading block"),
    ("speaking", "Open today's Speaking block"),
    ("writing", "Open today's Writing block when due"),
    ("check", "Review an email: /check followed by its text"),
    ("progress", "Show your learning profile"),
    ("export", "Export progress as md, csv, or json"),
    ("cancel", "Pause the active block safely"),
    ("reset", "Erase all progress after confirmation"),
    ("help", "Explain the daily practice loop"),
]

HELP_TEXT = (
    "🎓 <b>TOEFL iBT 2026 daily practice</b>\n\n"
    "At 08:00 Europe/Moscow I send one plan: Reading and Speaking every day, "
    "plus Writing every second calendar day. Complete the sections in any order.\n\n"
    "<b>Practice</b>\n"
    "/start — register and show today's plan.\n"
    "/today — today's persistent plan.\n"
    "/reading — Complete Words, Daily Life, or Academic Passage.\n"
    "/speaking — Listen and Repeat or Interview.\n"
    "/writing — Build a Sentence, Email, or Academic Discussion when due.\n"
    "/check &lt;email&gt; — review an email without changing today's practice.\n"
    "/cancel — pause without deleting submitted answers.\n\n"
    "<b>Profile</b>\n"
    "/progress — completion, scores, weak skills, and issue states.\n"
    "/export — Markdown profile; /export csv and /export json are also available.\n"
    "/reset — erase attempts and progress after confirmation.\n"
    "/help — show this guide."
)


def _today(svc: Services):
    return datetime.now(ZoneInfo(svc.settings.tz)).date()


def _as_entry(attempt: Attempt) -> PlanEntry:
    return PlanEntry(
        id=attempt.plan_id,
        section=attempt.section,
        task_id=attempt.task_id,
        task_type=attempt.task_type,
        status=attempt.status,
        payload=attempt.payload,
    )


def _safe(value: object, limit: int = 180) -> str:
    return html.escape(str(value)[:limit])


def _answer_keyboard(attempt: Attempt) -> list[list[tuple[str, str]]]:
    question = attempt.payload["questions"][attempt.current_item]
    return [
        [(f"{index + 1}. {option}", f"answer:{attempt.id}:{attempt.current_item}:{index}")]
        for index, option in enumerate(question["options"])
    ]


def _draft_keyboard(svc: Services, attempt: Attempt) -> list[list[tuple[str, str]]]:
    item = attempt.payload["items"][attempt.current_item]
    selected = svc.repo.attempt_draft(attempt.id)
    rows = [
        [(fragment, f"fragment:{attempt.id}:{attempt.current_item}:{index}")]
        for index, fragment in enumerate(item["fragments"])
        if index not in selected
    ]
    rows.append(
        [
            ("↩ Undo", f"draftundo:{attempt.id}"),
            ("Clear", f"draftclear:{attempt.id}"),
            ("Submit", f"draftsubmit:{attempt.id}"),
        ]
    )
    return rows


async def _show_plan(svc: Services, user_id: int) -> None:
    plan = svc.planner.ensure_plan(user_id, _today(svc))
    text, keyboard = render_plan(plan)
    await svc.notifier.send(user_id, text, keyboard)


async def _send_audio(
    svc: Services, bot: object | None, user_id: int, attempt: Attempt
) -> float | None:
    if bot is None:
        await svc.notifier.send(user_id, "Audio transport is unavailable; your place is saved.")
        return None
    texts = (
        attempt.payload["sentences"]
        if attempt.task_type is TaskType.LISTEN_REPEAT
        else attempt.payload["questions"]
    )
    text = str(texts[attempt.current_item])
    paths = attempt.payload.get("audio_paths", [])
    try:
        if (
            attempt.task_type is not TaskType.LISTEN_REPEAT
            and attempt.current_item < len(paths)
            and Path(paths[attempt.current_item]).exists()
        ):
            path = Path(paths[attempt.current_item])
        else:
            cache_base = (
                svc.settings.data_path
                / "audio_cache"
                / "tts-v3"
                / attempt.task_id
                / f"{attempt.current_item}.wav"
            )
            cached_ogg = cache_base.with_suffix(".ogg")
            if cached_ogg.exists():
                path = cached_ogg
            elif cache_base.exists():
                path = cache_base
            else:
                path = await svc.synthesizer.synthesize(text, cache_base)
        if attempt.task_type is TaskType.LISTEN_REPEAT:
            cue_path = (
                svc.settings.data_path
                / "audio_cache"
                / "listen-repeat-cue-v3"
                / attempt.task_id
                / f"{attempt.current_item}.ogg"
            )
            path = await svc.audio_cues.add_terminal_beep(path, cue_path)
        duration_seconds = await svc.audio_cues.duration_seconds(path)
        from aiogram.types import FSInputFile

        await bot.send_voice(user_id, FSInputFile(str(path)))  # type: ignore[attr-defined]
        return duration_seconds
    except Exception:
        await svc.notifier.send(
            user_id,
            "Audio could not be prepared. The attempt and current item are saved; "
            "try this section again later.",
        )
        return None


async def _deliver(svc: Services, bot: object | None, user_id: int, attempt: Attempt) -> None:
    entry = _as_entry(attempt)
    keyboard = None
    if attempt.task_type in {TaskType.DAILY_LIFE, TaskType.ACADEMIC_PASSAGE}:
        keyboard = _answer_keyboard(attempt)
    elif attempt.task_type is TaskType.BUILD_SENTENCE:
        keyboard = _draft_keyboard(svc, attempt)
    await svc.notifier.send(user_id, render_prompt(entry, attempt.current_item), keyboard)
    if attempt.task_type in {TaskType.LISTEN_REPEAT, TaskType.INTERVIEW}:
        if attempt.task_type is TaskType.LISTEN_REPEAT:
            await svc.notifier.send(user_id, "🔇 Слушайте. Пока не говорите.")
        audio_duration = await _send_audio(svc, bot, user_id, attempt)
        if attempt.task_type is TaskType.LISTEN_REPEAT and audio_duration is not None:
            await asyncio.sleep(audio_duration + 0.3)
            await svc.notifier.send(user_id, "🎙 Можно говорить. Повторите фразу один раз.")
        elif attempt.task_type is TaskType.INTERVIEW and audio_duration is not None:
            svc.engine.arm_interview_deadline(
                user_id, attempt.id, attempt.current_item, now=datetime.now(UTC)
            )


async def _open_entry(svc: Services, bot: object | None, user_id: int, plan_id: int) -> None:
    try:
        attempt = svc.engine.start(user_id, plan_id)
    except ActivePracticeError as exc:
        active = svc.engine.active(user_id)
        await svc.notifier.send(
            user_id,
            (
                f"Another block is active ({active.section.value}). Finish it or use /cancel first."
                if active
                else str(exc)
            ),
        )
        return
    await _deliver(svc, bot, user_id, attempt)


async def _open_section(svc: Services, bot: object | None, user_id: int, section: Section) -> None:
    plan = svc.planner.ensure_plan(user_id, _today(svc))
    entry = plan.entry(section)
    if entry is None:
        await svc.notifier.send(user_id, f"{section.value.title()} is not due today.")
        return
    if entry.status == "complete":
        await svc.notifier.send(
            user_id, f"Today's {section.value.title()} block is already complete."
        )
        return
    await _open_entry(svc, bot, user_id, entry.id)


async def _after_submit(svc: Services, bot: object | None, user_id: int, attempt: Attempt) -> None:
    if attempt.status == "active":
        await _deliver(svc, bot, user_id, attempt)
        return
    evaluation_note = ""
    evaluation = None
    if attempt.evaluation_state == "pending":
        evaluation = await svc.evaluator.evaluate(attempt.id)
        if evaluation is None:
            evaluation_note = (
                "\nYour answer is saved; rubric evaluation is pending and will retry automatically."
            )
        attempt = svc.engine.get_attempt(attempt.id)
    score = (
        f"{attempt.raw_score:g}/{attempt.max_score:g}"
        if attempt.raw_score is not None
        else "pending"
    )
    keyboard = [
        [("Fix mistakes", "fix:active"), ("Next due section", "next:due")],
        [("Export", "export:md"), ("Back to today's plan", "plan:today")],
    ]
    review = _attempt_review(svc, attempt, evaluation)
    text = f"✅ <b>Block complete</b>\nTraining score: <b>{score}</b>{evaluation_note}{review}"
    await svc.notifier.send(user_id, text, keyboard)


def _attempt_review(svc: Services, attempt: Attempt, evaluation: object | None) -> str:
    items = svc.repo.attempt_items(attempt.id)
    missed: list[str] = []
    for item in items:
        score = item["score"]
        maximum = item["max_score"]
        if score is None or float(score) >= float(maximum or 0):
            continue
        feedback = json.loads(str(item["feedback_json"]))
        correct = json.loads(str(item["correct_json"]))
        index = int(item["item_index"]) + 1
        response = _safe(item["response_text"])
        if attempt.task_type in {TaskType.DAILY_LIFE, TaskType.ACADEMIC_PASSAGE}:
            question = attempt.payload["questions"][index - 1]
            answer = question["options"][int(correct)]
            missed.append(
                f"{index}. {_safe(answer)} — "
                f"{_safe(feedback.get('evidence', ''))} "
                f"({_safe(feedback.get('explanation', ''))})"
            )
        elif attempt.task_type is TaskType.COMPLETE_WORDS:
            expected = feedback.get("expected", correct)
            received = feedback.get("received", [])
            missed.append(
                "Expected: "
                + _safe(", ".join(str(value) for value in expected))
                + "\nYour endings: "
                + _safe(", ".join(str(value) for value in received))
            )
        else:
            missed.append(f"{index}. {response or 'incomplete'} → {_safe(correct)}")
    if evaluation is not None:
        explanation = _safe(getattr(evaluation, "explanation", ""))
        issues = getattr(evaluation, "issues", [])
        for issue in issues:
            missed.append(
                f"{_safe(issue.original_excerpt)} → {_safe(issue.correction)} "
                f"({_safe(issue.explanation)})"
            )
        if explanation:
            missed.insert(0, explanation)
    if not missed:
        return "\n\nNo mistakes in this block."
    return "\n\n<b>Review</b>\n" + "\n".join(f"• {line}" for line in missed)


async def _submit(
    svc: Services,
    bot: object | None,
    user_id: int,
    response: str,
    *,
    metrics: dict[str, object] | None = None,
    now: datetime | None = None,
) -> None:
    try:
        attempt = svc.engine.submit_current(user_id, response, metrics=metrics, now=now)
    except LookupError:
        await svc.notifier.send(user_id, "No active block. Open /today to start one.")
        return
    await _after_submit(svc, bot, user_id, attempt)


def _email_feedback_blocks(result: EmailCheckResult) -> list[str]:
    blocks = [f"✅ <b>Email review</b>\n{_safe(result.overall_assessment, 800)}"]
    if result.strengths:
        strengths = "\n".join(f"• {_safe(value, 500)}" for value in result.strengths)
        blocks.append(f"<b>Strengths</b>\n{strengths}")
    if result.issues:
        for issue in result.issues:
            blocks.append(
                "<b>Correction</b>\n"
                f"{_safe(issue.original_excerpt, 500)} → {_safe(issue.correction, 500)}\n"
                f"{_safe(issue.explanation, 700)}"
            )
    else:
        blocks.append("<b>Corrections</b>\nNo clear errors found.")
    return blocks


def _pack_html_blocks(blocks: list[str], limit: int = 3800) -> list[str]:
    messages: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if current and len(candidate) > limit:
            messages.append(current)
            current = block
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def _escaped_chunks(value: str, limit: int = 3500) -> list[str]:
    chunks: list[str] = []
    current = ""
    for character in value:
        escaped = html.escape(character)
        if current and len(current) + len(escaped) > limit:
            chunks.append(current)
            current = ""
        current += escaped
    if current:
        chunks.append(current)
    return chunks or [""]


async def _check_email(svc: Services, user_id: int, email_text: str) -> None:
    email_text = email_text.strip()
    if not email_text:
        await svc.notifier.send(
            user_id,
            "Usage: <code>/check Dear Coordinator, ...</code>",
        )
        return
    result = await svc.email_checker.check(user_id, email_text)
    if result is None:
        await svc.notifier.send(user_id, "Email check failed. Please try again later.")
        return
    for message in _pack_html_blocks(_email_feedback_blocks(result)):
        await svc.notifier.send(user_id, message)
    chunks = _escaped_chunks(result.revised_email)
    for index, chunk in enumerate(chunks):
        heading = "✏️ <b>Revised email</b>\n" if index == 0 else ""
        await svc.notifier.send(user_id, f"{heading}<pre>{chunk}</pre>")


def build_router(svc: Services, bot: object | None = None) -> Router:
    router = Router()
    router.message.filter(F.from_user.id == svc.settings.admin_user_id)
    router.callback_query.filter(F.from_user.id == svc.settings.admin_user_id)

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        svc.repo.ensure_subscriber(message.from_user.id)
        await _show_plan(svc, message.from_user.id)

    @router.message(Command("today"))
    async def on_today(message: Message) -> None:
        await _show_plan(svc, message.from_user.id)

    @router.message(Command("reading"))
    async def on_reading(message: Message) -> None:
        await _open_section(svc, bot, message.from_user.id, Section.READING)

    @router.message(Command("speaking"))
    async def on_speaking(message: Message) -> None:
        await _open_section(svc, bot, message.from_user.id, Section.SPEAKING)

    @router.message(Command("writing"))
    async def on_writing(message: Message) -> None:
        await _open_section(svc, bot, message.from_user.id, Section.WRITING)

    @router.message(Command("check"))
    async def on_check(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        email_text = parts[1] if len(parts) == 2 else ""
        await _check_email(svc, message.from_user.id, email_text)

    @router.message(Command("progress"))
    async def on_progress(message: Message) -> None:
        report = progress_markdown(svc.repo, message.from_user.id, today=_today(svc))
        escaped = html.escape(report)
        await message.answer(f"<pre>{escaped[:3900]}</pre>")

    @router.message(Command("export"))
    async def on_export(message: Message) -> None:
        fmt = (message.text or "").partition(" ")[2].strip().lower() or "md"
        try:
            path = export_progress(
                svc.repo, message.from_user.id, fmt, svc.settings.data_path / "exports"
            )
        except ValueError:
            await message.answer("Use /export, /export csv, or /export json.")
            return
        await svc.notifier.send_file(message.from_user.id, path, "Current TOEFL learning profile")

    @router.message(Command("cancel"))
    async def on_cancel(message: Message) -> None:
        paused = svc.engine.cancel(message.from_user.id)
        await message.answer(
            "Active block paused; submitted answers are saved."
            if paused
            else "No active block to pause."
        )

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("reset"))
    async def on_reset(message: Message) -> None:
        await svc.notifier.send(
            message.from_user.id,
            "⚠️ <b>Erase all TOEFL attempts, plans, issues, and skill progress?</b>\n"
            "This cannot be undone.",
            reset_confirm(),
        )

    @router.callback_query(F.data.startswith("practice:"))
    async def on_practice(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        await _open_entry(svc, bot, cb.from_user.id, int(cb.data.split(":")[1]))

    @router.callback_query(F.data.startswith("answer:"))
    async def on_answer(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        _, attempt_id, item_index, choice = cb.data.split(":")
        try:
            attempt = svc.engine.submit(
                cb.from_user.id, int(attempt_id), int(item_index), f"@{choice}"
            )
        except (LookupError, ActivePracticeError):
            await svc.notifier.send(cb.from_user.id, "That attempt is no longer active.")
            return
        await _after_submit(svc, bot, cb.from_user.id, attempt)

    @router.callback_query(F.data.startswith("fragment:"))
    async def on_fragment(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        _, attempt_id, item_index, fragment_index = cb.data.split(":")
        attempt = svc.engine.active(cb.from_user.id)
        if not attempt or attempt.id != int(attempt_id) or attempt.current_item != int(item_index):
            return
        svc.repo.append_attempt_draft(attempt.id, int(fragment_index))
        await svc.notifier.send(
            cb.from_user.id,
            "Current: " + svc.repo.render_attempt_draft(attempt.id),
            _draft_keyboard(svc, attempt),
        )

    @router.callback_query(F.data.startswith("draftundo:"))
    async def on_draft_undo(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        callback_attempt_id = int(cb.data.split(":")[1])
        attempt = svc.engine.active(cb.from_user.id)
        if attempt and attempt.id == callback_attempt_id:
            svc.repo.undo_attempt_draft(attempt.id)
            await svc.notifier.send(
                cb.from_user.id,
                "Current: " + svc.repo.render_attempt_draft(attempt.id),
                _draft_keyboard(svc, attempt),
            )

    @router.callback_query(F.data.startswith("draftclear:"))
    async def on_draft_clear(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        callback_attempt_id = int(cb.data.split(":")[1])
        attempt = svc.engine.active(cb.from_user.id)
        if attempt and attempt.id == callback_attempt_id:
            svc.repo.clear_attempt_draft(attempt.id)
            await svc.notifier.send(
                cb.from_user.id, "Sentence cleared.", _draft_keyboard(svc, attempt)
            )

    @router.callback_query(F.data.startswith("draftsubmit:"))
    async def on_draft_submit(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        callback_attempt_id = int(cb.data.split(":")[1])
        attempt = svc.engine.active(cb.from_user.id)
        if not attempt or attempt.id != callback_attempt_id:
            return
        response = svc.repo.render_attempt_draft(attempt.id)
        if not response:
            await svc.notifier.send(cb.from_user.id, "Choose at least one fragment first.")
            return
        await _submit(svc, bot, cb.from_user.id, response)

    @router.callback_query(F.data == "plan:today")
    async def on_plan(cb: CallbackQuery) -> None:
        await cb.answer()
        await _show_plan(svc, cb.from_user.id)

    @router.callback_query(F.data == "next:due")
    async def on_next(cb: CallbackQuery) -> None:
        await cb.answer()
        plan = svc.planner.ensure_plan(cb.from_user.id, _today(svc))
        entry = next((entry for entry in plan.entries if entry.status != "complete"), None)
        if entry:
            await _open_entry(svc, bot, cb.from_user.id, entry.id)
        else:
            await _show_plan(svc, cb.from_user.id)

    @router.callback_query(F.data.startswith("export:"))
    async def on_export_cb(cb: CallbackQuery) -> None:
        await cb.answer()
        fmt = cb.data.split(":")[1]
        path = export_progress(svc.repo, cb.from_user.id, fmt, svc.settings.data_path / "exports")
        await svc.notifier.send_file(cb.from_user.id, path, "Current TOEFL learning profile")

    @router.callback_query(F.data == "fix:active")
    async def on_fix(cb: CallbackQuery) -> None:
        await cb.answer()
        issues = svc.repo.conn.execute(
            """
            SELECT canonical_key, original_excerpt, correction FROM learning_issue
            WHERE user_id=? AND state!='resolved' ORDER BY last_seen DESC LIMIT 5
            """,
            (cb.from_user.id,),
        ).fetchall()
        text = (
            "\n".join(
                f"• {html.escape(str(row['canonical_key']))}: "
                f"{html.escape(str(row['original_excerpt']))} → "
                f"{html.escape(str(row['correction']))}"
                for row in issues
            )
            or "No active mistakes to fix yet."
        )
        await svc.notifier.send(cb.from_user.id, "<b>Focused review</b>\n" + text)

    @router.callback_query(F.data.startswith("reset:"))
    async def on_reset_cb(cb: CallbackQuery) -> None:
        await cb.answer()
        if not svc.repo.claim_callback(cb.id, cb.from_user.id):
            return
        if cb.data.endswith(":confirm"):
            counts = svc.repo.reset_progress(cb.from_user.id)
            await svc.notifier.send(
                cb.from_user.id, f"✅ Progress erased ({sum(counts.values())} records)."
            )
        else:
            await svc.notifier.send(cb.from_user.id, "Reset cancelled.")

    @router.message(F.voice)
    async def on_voice(message: Message) -> None:
        received_at = message.date
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        else:
            received_at = received_at.astimezone(UTC)
        attempt = svc.engine.active(message.from_user.id)
        if not attempt or attempt.task_type not in {TaskType.LISTEN_REPEAT, TaskType.INTERVIEW}:
            await message.answer("A voice response is accepted only inside today's Speaking block.")
            return
        if bot is None:
            await message.answer("Voice download is unavailable; your attempt is saved.")
            return
        with tempfile.TemporaryDirectory(prefix="toefl-voice-") as temp_dir:
            path = Path(temp_dir) / "answer.ogg"
            await bot.download(message.voice.file_id, destination=path)  # type: ignore[attr-defined]
            try:
                transcript = await svc.transcriber.transcribe(path, lang="en")
            except Exception:
                await message.answer(
                    "Transcription failed; the item is saved. "
                    "Send the voice message again to retry."
                )
                return
        await message.answer(f"📝 <i>{html.escape(transcript)}</i>")
        duration = max(float(message.voice.duration or 0), 0.1)
        words = len(transcript.split())
        metrics: dict[str, object] = {
            "duration_seconds": duration,
            "word_count": words,
            "words_per_minute": round(words * 60 / duration, 1),
            "recognition_confidence": None,
            "received_at": received_at.isoformat(),
        }
        if attempt.deadline_at:
            metrics["late"] = received_at > attempt.deadline_at
        await _submit(
            svc,
            bot,
            message.from_user.id,
            transcript,
            metrics=metrics,
            now=received_at,
        )

    @router.message(F.text)
    async def on_text(message: Message) -> None:
        attempt = svc.engine.active(message.from_user.id)
        if not attempt:
            await message.answer("Open /today to start a TOEFL block.")
            return
        if attempt.task_type in {TaskType.LISTEN_REPEAT, TaskType.INTERVIEW}:
            await message.answer("Please answer this Speaking item with one voice message.")
            return
        await _submit(svc, bot, message.from_user.id, message.text or "")

    return router
