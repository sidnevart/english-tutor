"""Interactive in-chat comprehension quiz (reading & listening).

Wires the previously test-only `pipeline.build_evaluation` to the bot: the
learner taps "Start quiz" on a delivered item, answers one question at a time
with inline A–D buttons (multi-select for TOEFL "summary" questions), and the
flow grades each answer, shows the explanation, and on the last question calls
`pipeline.finalize_review` (Anki cards for misses, REVIEWED status, topic
progress). Quiz position lives in aiogram's in-memory FSM.
"""

from __future__ import annotations

import time
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tutor.bot.keyboards import quiz_options
from tutor.domain.enums import ContentType
from tutor.domain.models import Quiz, QuizQuestion
from tutor.eval.grader import indices_to_mask, is_correct, mask_to_indices
from tutor.factory import Services
from tutor.pipeline import build_evaluation, finalize_review
from tutor.render import render_question, render_score


class QuizState(StatesGroup):
    active = State()


def _recommended_min(svc: Services, content_type: ContentType) -> int:
    if content_type == ContentType.PODCAST:
        return svc.settings.listening_time_min
    return svc.settings.reading_time_min


async def start_quiz(
    svc: Services, bot: Any, user_id: int, state: FSMContext, content_id: int
) -> None:
    """Build (if needed) and present the comprehension quiz for an item."""
    content = svc.repo.get(content_id)
    if content is None:
        await svc.notifier.send(user_id, "That material isn't available anymore.")
        return

    quiz = svc.repo.get_quiz_auto(content_id)
    if quiz is None or not quiz.questions:
        await svc.notifier.send(user_id, "📝 Building your quiz — one moment…")
        try:
            quiz = await build_evaluation(svc, content_id, user_id)
        except Exception:  # noqa: BLE001
            await svc.notifier.send(
                user_id, "Couldn't build a quiz for this item. Try again later."
            )
            return
    if not quiz.questions:
        await svc.notifier.send(user_id, "Couldn't build a quiz for this item. Try again later.")
        return

    kind = "🎧 Listening" if content.content_type == ContentType.PODCAST else "📖 Reading"
    rec = _recommended_min(svc, content.content_type)
    await svc.notifier.send(
        user_id,
        f"{kind} quiz · {len(quiz.questions)} questions · ~{rec} min recommended.\n"
        "Answer each question with the buttons below.",
    )

    await state.set_state(QuizState.active)
    await state.update_data(
        content_id=content_id,
        qids=[q.id for q in quiz.questions],
        idx=0,
        selections=[],
        started_at=time.time(),
    )
    await _present_question(svc, user_id, state, quiz, 0)


def _current_quiz(svc: Services, content_id: int) -> Quiz | None:
    return svc.repo.get_quiz_auto(content_id)


def _question_by_index(quiz: Quiz, idx: int) -> QuizQuestion | None:
    if 0 <= idx < len(quiz.questions):
        return quiz.questions[idx]
    return None


async def _present_question(
    svc: Services,
    user_id: int,
    state: FSMContext,
    quiz: Quiz,
    idx: int,
    selected: list[int] | None = None,
) -> None:
    q = _question_by_index(quiz, idx)
    if q is None:
        return
    text = render_question(idx, len(quiz.questions), q)
    if q.is_multi:
        text += "\n\n<i>Select all that apply (usually 3), then tap Submit.</i>"
    keyboard = quiz_options(len(q.options), multi=q.is_multi, selected=selected or [])
    await svc.notifier.send(user_id, text, keyboard)


async def handle_option(
    svc: Services, bot: Any, user_id: int, state: FSMContext, option_index: int
) -> None:
    """Handle a tap on an option button for the current question."""
    data = await state.get_data()
    content_id = data.get("content_id")
    idx = int(data.get("idx", 0))
    if content_id is None:
        return
    quiz = _current_quiz(svc, content_id)
    if quiz is None:
        await state.clear()
        return
    q = _question_by_index(quiz, idx)
    if q is None:
        return
    if option_index < 0 or option_index >= len(q.options):
        return

    if q.is_multi:
        # Toggle the selection and re-render (no advance until Submit).
        selections = list(data.get("selections", []))
        if option_index in selections:
            selections.remove(option_index)
        else:
            selections.append(option_index)
        await state.update_data(selections=selections)
        await _present_question(svc, user_id, state, quiz, idx, selected=selections)
        return

    # Single-select: record and advance.
    correct = is_correct(q, option_index)
    if q.id is not None:
        svc.repo.record_attempt(q.id, user_id, option_index, correct)
    await _feedback(svc, user_id, q, chosen_index=option_index, correct=correct)
    await _advance(svc, user_id, state, quiz, idx)


async def handle_submit(svc: Services, bot: Any, user_id: int, state: FSMContext) -> None:
    """Handle the Submit button for a multi-select (summary) question."""
    data = await state.get_data()
    content_id = data.get("content_id")
    idx = int(data.get("idx", 0))
    if content_id is None:
        return
    quiz = _current_quiz(svc, content_id)
    if quiz is None:
        await state.clear()
        return
    q = _question_by_index(quiz, idx)
    if q is None or not q.is_multi:
        return
    selections = sorted(set(data.get("selections", [])))
    if not selections:
        await svc.notifier.send(user_id, "Select at least one option before submitting.")
        return
    mask = indices_to_mask(selections)
    correct = is_correct(q, mask)
    if q.id is not None:
        svc.repo.record_attempt(q.id, user_id, mask, correct)
    await _feedback(svc, user_id, q, chosen_mask=mask, correct=correct)
    await state.update_data(selections=[])
    await _advance(svc, user_id, state, quiz, idx)


def _letter(i: int) -> str:
    return "ABCDEFGH"[i] if i < 8 else str(i + 1)


async def _feedback(
    svc: Services,
    user_id: int,
    q: QuizQuestion,
    *,
    chosen_index: int | None = None,
    chosen_mask: int | None = None,
    correct: bool,
) -> None:
    if q.is_multi:
        right = ", ".join(_letter(i) for i in q.correct_indices)
        head = "✅ Correct!" if correct else f"❌ Correct answers: <b>{right}</b>"
    else:
        right = _letter(q.correct_index)
        head = "✅ Correct!" if correct else f"❌ Correct answer: <b>{right}</b>"
    parts = [head]
    if q.explanation:
        parts.append(f"<i>{q.explanation}</i>")
    await svc.notifier.send(user_id, "\n".join(parts))


async def _advance(svc: Services, user_id: int, state: FSMContext, quiz: Quiz, idx: int) -> None:
    next_idx = idx + 1
    if next_idx < len(quiz.questions):
        await state.update_data(idx=next_idx)
        await _present_question(svc, user_id, state, quiz, next_idx)
        return

    # Quiz finished: grade from recorded attempts, export cards, mark reviewed.
    data = await state.get_data()
    content_id = int(data.get("content_id"))
    started_at = float(data.get("started_at", 0.0)) or time.time()
    await state.clear()

    result = await finalize_review(svc, content_id, user_id)
    elapsed_min = max(0, round((time.time() - started_at) / 60))
    await svc.notifier.send(
        user_id,
        render_score(result.correct, result.total) + f"\n⏱ Time: ~{elapsed_min} min.",
    )
    if result.anki.apkg_path:
        from pathlib import Path

        await svc.notifier.send_file(
            user_id, Path(result.anki.apkg_path), caption="🎴 Your Anki cards for this set"
        )


__all__ = [
    "QuizState",
    "start_quiz",
    "handle_option",
    "handle_submit",
    "mask_to_indices",
]
