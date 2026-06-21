"""aiogram handlers: content delivery, on-demand quiz, and conversation practice.

Quiz progress is DB-derived (restart-safe). Speaking/discussion run as multi-turn
FSM sessions via `tutor.bot.conversation`. Handler order matters: commands and
callbacks are registered before the catch-all in-session message handlers.
"""

from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from tutor.bot.conversation import (
    ConversationState,
    download_voice,
    end_session,
    handle_turn,
    start_discussion,
    start_speaking,
)
from tutor.bot.keyboards import answer_options
from tutor.domain.enums import DeliveryStatus, QuizKind
from tutor.domain.models import Card
from tutor.eval.grader import is_correct
from tutor.factory import Services
from tutor.memory import Memory
from tutor.pipeline import build_evaluation, deliver_new, finalize_review
from tutor.render import render_question, render_score

_COACH_SYSTEM_SUFFIX = (
    "\n\nReply conversationally, keep it short, and gently correct the learner's English."
)

# Terse one-liners for the Telegram slash menu (set_my_commands). Telegram caps
# these and shows one per line, so the human-readable detail lives in HELP_TEXT.
COMMANDS: list[tuple[str, str]] = [
    ("start", "Today's material + quiz"),
    ("next", "Next reading or episode"),
    ("speak", "Speaking practice (voice)"),
    ("stop", "End the current practice session"),
    ("coach", "Ask a quick question"),
    ("cards", "Re-send your Anki deck"),
    ("progress", "Your stats"),
    ("help", "Show available commands"),
]

# Rich, grouped /help body. HTML parse mode → escape & < > (e.g. &lt;question&gt;).
HELP_TEXT = (
    "🎓 <b>TOEFL coach — help</b>\n\n"
    "<b>📚 Content</b>\n"
    "/start — register and deliver today's first reading or episode "
    "(with its words &amp; idioms Anki deck) and a quiz button\n"
    "/next — deliver the next reading or episode the same way\n"
    "Tap <b>📖 Quiz me</b> under any item for a 3-question comprehension quiz.\n\n"
    "<b>🎙 Speaking &amp; dialog</b>\n"
    "/speak — start a spoken practice session: I set a TOEFL-style task, you "
    "answer by voice or text, and we go back and forth\n"
    "/coach &lt;question&gt; — a quick one-off question "
    "(e.g. <code>/coach what does 'ubiquitous' mean?</code>); I answer and "
    "gently correct your English\n"
    "/stop — end the current /speak or discussion session and get short feedback\n\n"
    "<b>📊 Tracking</b>\n"
    "/cards — re-send your full Anki deck as an .apkg file\n"
    "/progress — your stats: cards generated, delivered, reviewed, queued\n\n"
    "<i>Tip: in the evening reminder, tap “💬 Discuss today's material” to talk "
    "about the day's article or episode. A plain voice message any time gets a "
    "quick coach reply.</i>"
)


async def _send_next_question(svc: Services, user_id: int, content_id: int) -> bool:
    quiz = svc.repo.get_quiz(content_id, QuizKind.READING)
    if quiz is None:
        return False
    answered = {a.quiz_question_id for a in svc.repo.attempts_for_content(content_id, user_id)}
    pending = [(i, q) for i, q in enumerate(quiz.questions) if q.id not in answered]
    if not pending:
        return False
    idx, q = pending[0]
    text = render_question(idx, len(quiz.questions), q)
    await svc.notifier.send(user_id, text, keyboard=answer_options(content_id, q.id, q.options))
    return True


async def _finalize(svc: Services, user_id: int, content_id: int) -> None:
    content = svc.repo.get(content_id)
    if content is None or content.status == DeliveryStatus.REVIEWED:
        return
    result = await finalize_review(svc, content_id, user_id)
    await svc.notifier.send(user_id, render_score(result.correct, result.total))


async def _coach_reply(svc: Services, user_id: int, utterance: str) -> str:
    mem = Memory(svc.settings.soul_dir, user_id)
    return await svc.llm.complete(mem.persona() + _COACH_SYSTEM_SUFFIX, utterance)


def build_router(svc: Services, bot: object | None = None) -> Router:
    router = Router()

    # ---- commands ----
    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        user = message.from_user.id
        svc.repo.ensure_subscriber(user)
        await message.answer(
            "👋 <b>TOEFL coach</b>\n"
            "• today's readings/episodes come with an Anki deck (words & idioms)\n"
            "• tap “📖 Quiz me” for a comprehension quiz\n"
            "• /speak for speaking practice · /progress for your stats"
        )
        if not await deliver_new(svc, user, limit=1):
            await message.answer("No new material right now. Try /next later.")

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("speak"))
    async def on_speak(message: Message, state: FSMContext) -> None:
        await start_speaking(svc, bot, message.from_user.id, state)

    @router.message(Command("stop"))
    async def on_stop(message: Message, state: FSMContext) -> None:
        if await state.get_state() is None:
            await message.answer("Nothing to stop — start with /speak.")
            return
        await end_session(svc, message.from_user.id, state)

    @router.message(Command("next"))
    async def on_next(message: Message) -> None:
        if not await deliver_new(svc, message.from_user.id, limit=1):
            await message.answer("No new material. It refreshes each morning.")

    @router.message(Command("coach"))
    async def on_coach(message: Message) -> None:
        utterance = (message.text or "").partition(" ")[2].strip()
        if not utterance:
            await message.answer(
                "Ask me anything, e.g. <code>/coach what does 'ubiquitous' mean?</code>"
            )
            return
        await message.answer(await _coach_reply(svc, message.from_user.id, utterance))

    @router.message(Command("cards"))
    async def on_cards(message: Message) -> None:
        user = message.from_user.id
        pairs = svc.repo.get_anki_cards(user)
        if not pairs:
            await message.answer("No Anki cards yet — they come with each reading/episode.")
            return
        cards = [Card(front=f, back=b, tags=["toefl"]) for f, b in pairs]
        result = await svc.anki.add_cards(svc.settings.anki_deck, cards)
        if result.apkg_path:
            await svc.notifier.send_file(
                user, Path(result.apkg_path), caption=f"🎴 {len(cards)} cards to review"
            )

    @router.message(Command("progress"))
    async def on_progress(message: Message) -> None:
        user = message.from_user.id
        new = svc.repo.count_status(user, DeliveryStatus.NEW)
        delivered = svc.repo.count_status(user, DeliveryStatus.DELIVERED)
        reviewed = svc.repo.count_status(user, DeliveryStatus.REVIEWED)
        cards = svc.repo.anki_card_count(user)
        await message.answer(
            "📊 <b>Your progress</b>\n"
            f"• Anki cards generated: <b>{cards}</b>\n"
            f"• Delivered (awaiting practice): <b>{delivered}</b>\n"
            f"• Quizzed/reviewed: <b>{reviewed}</b>\n"
            f"• Queued for delivery: <b>{new}</b>\n\n"
            "Review your cards in the Anki app 📚"
        )

    # ---- callbacks ----
    @router.callback_query(F.data.startswith("discuss:"))
    async def on_discuss(cb: CallbackQuery, state: FSMContext) -> None:
        await cb.answer()
        await start_discussion(svc, bot, cb.from_user.id, state, int(cb.data.split(":")[1]))

    @router.callback_query(F.data == "speak:start")
    async def on_speak_cb(cb: CallbackQuery, state: FSMContext) -> None:
        await cb.answer()
        await start_speaking(svc, bot, cb.from_user.id, state)

    @router.callback_query(F.data.startswith("quiz:"))
    async def on_quiz(cb: CallbackQuery) -> None:
        await cb.answer()
        user = cb.from_user.id
        content_id = int(cb.data.split(":")[1])
        if svc.repo.get_quiz(content_id, QuizKind.READING) is None:
            await build_evaluation(svc, content_id, user)
        if not await _send_next_question(svc, user, content_id):
            await _finalize(svc, user, content_id)

    @router.callback_query(F.data.startswith("ans:"))
    async def on_answer(cb: CallbackQuery) -> None:
        user = cb.from_user.id
        _, scid, sqid, schosen = cb.data.split(":")
        content_id, qid, chosen = int(scid), int(sqid), int(schosen)

        quiz = svc.repo.get_quiz(content_id, QuizKind.READING)
        question = next((q for q in quiz.questions if q.id == qid), None) if quiz else None
        if question is None:
            await cb.answer("This quiz has expired.")
            return
        answered = {a.quiz_question_id for a in svc.repo.attempts_for_content(content_id, user)}
        if qid in answered:
            await cb.answer("Already answered.")
            return

        ok = is_correct(question, chosen)
        svc.repo.record_attempt(qid, user, chosen, ok)
        await cb.answer("✅ Correct!" if ok else "❌ Not quite.")

        letters = "ABCDEFGH"
        correct_letter = letters[question.correct_index]
        correct_opt = question.options[question.correct_index]
        if ok:
            verdict = f"✅ Correct — <b>{correct_letter}. {correct_opt}</b>"
        else:
            chosen_letter = letters[chosen] if 0 <= chosen < len(question.options) else "?"
            verdict = (
                f"❌ You chose <b>{chosen_letter}</b>. "
                f"Correct: <b>{correct_letter}. {correct_opt}</b>"
            )
        if cb.message is not None:
            try:
                await cb.message.edit_text(
                    f"{question.prompt}\n\n{verdict}\n\n<i>{question.explanation}</i>"
                )
            except Exception:  # noqa: BLE001 — editing an old message can fail; ignore
                pass

        if not await _send_next_question(svc, user, content_id):
            await _finalize(svc, user, content_id)

    # ---- in-session messages (registered last so commands win) ----
    @router.message(ConversationState.active, F.voice)
    async def on_session_voice(message: Message, state: FSMContext) -> None:
        if bot is None:
            await message.answer("Voice isn't available right now.")
            return
        text = await download_voice(bot, svc, message)
        await message.answer(f"📝 <i>{text}</i>")
        await handle_turn(svc, bot, message.from_user.id, state, text)

    @router.message(ConversationState.active, F.text)
    async def on_session_text(message: Message, state: FSMContext) -> None:
        await handle_turn(svc, bot, message.from_user.id, state, message.text or "")

    @router.message(F.voice)
    async def on_voice(message: Message) -> None:
        if bot is None:
            await message.answer("Voice practice isn't available right now. Try /speak.")
            return
        text = await download_voice(bot, svc, message)
        reply = await _coach_reply(svc, message.from_user.id, f"The learner said: {text}")
        await message.answer(f"📝 <i>{text}</i>\n\n{reply}")

    return router
