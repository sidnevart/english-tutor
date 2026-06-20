"""aiogram handlers wiring the inline-keyboard quiz flow over the pipeline.

Quiz progress is derived from the `attempt` table (DB is truth), not from FSM
memory, so the flow survives a bot restart mid-quiz.
"""

from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from tutor.bot.keyboards import answer_options
from tutor.domain.enums import DeliveryStatus, QuizKind
from tutor.eval.grader import is_correct
from tutor.factory import Services
from tutor.pipeline import build_evaluation, deliver_new, finalize_review
from tutor.render import render_score


async def _send_next_question(svc: Services, user_id: int, content_id: int) -> bool:
    """Send the first not-yet-answered question. Returns False if none remain."""
    quiz = svc.repo.get_quiz(content_id, QuizKind.READING)
    if quiz is None:
        return False
    answered = {a.quiz_question_id for a in svc.repo.attempts_for_content(content_id, user_id)}
    pending = [(i, q) for i, q in enumerate(quiz.questions) if q.id not in answered]
    if not pending:
        return False
    idx, q = pending[0]
    text = f"<b>Question {idx + 1}/{len(quiz.questions)}</b>\n\n{q.prompt}"
    await svc.notifier.send(user_id, text, keyboard=answer_options(content_id, q.id, q.options))
    return True


async def _finalize(svc: Services, user_id: int, content_id: int) -> None:
    content = svc.repo.get(content_id)
    if content is None or content.status == DeliveryStatus.REVIEWED:
        return
    result = await finalize_review(svc, content_id, user_id)
    await svc.notifier.send(user_id, render_score(result.correct, result.total))
    if result.anki.apkg_path:
        await svc.notifier.send_file(
            user_id, Path(result.anki.apkg_path), caption="🎴 Your Anki cards for today"
        )
    vocab = svc.repo.get_vocab(content_id)
    if vocab:
        lines = "\n".join(f"• <b>{v.word}</b>" for v in vocab)
        await svc.notifier.send(user_id, f"🧠 <b>Vocabulary from today</b>\n{lines}")


def build_router(svc: Services) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        user = message.from_user.id
        svc.repo.ensure_subscriber(user)
        await message.answer(
            "👋 <b>TOEFL coach</b>\nHere's your next reading — tap “📖 Quiz me” when ready."
        )
        if not await deliver_new(svc, user, limit=1):
            await message.answer("No new readings right now. Fetch more, then /next.")

    @router.message(Command("next"))
    async def on_next(message: Message) -> None:
        user = message.from_user.id
        if not await deliver_new(svc, user, limit=1):
            await message.answer("No new readings. Run `tutor scrape` to fetch more.")

    @router.callback_query(F.data.startswith("quiz:"))
    async def on_quiz(cb: CallbackQuery) -> None:
        await cb.answer()
        user = cb.from_user.id
        content_id = int(cb.data.split(":")[1])
        if svc.repo.get_quiz(content_id, QuizKind.READING) is None:
            await build_evaluation(svc, content_id)
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

        correct_opt = question.options[question.correct_index]
        verdict = "✅ Correct!" if ok else f"❌ Correct answer: {correct_opt}"
        if cb.message is not None:
            try:
                await cb.message.edit_text(
                    f"{question.prompt}\n\n{verdict}\n\n<i>{question.explanation}</i>"
                )
            except Exception:  # noqa: BLE001 — editing an old message can fail; ignore
                pass

        if not await _send_next_question(svc, user, content_id):
            await _finalize(svc, user, content_id)

    return router
