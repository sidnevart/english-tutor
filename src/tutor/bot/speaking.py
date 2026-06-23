"""Strict TOEFL Speaking sessions: timed tasks with rubric scoring.

A task is generated, its reading/listening delivered (listening is read aloud via
TTS), and the official preparation/response timers run as background nudges. The
learner answers by voice (transcribed via STT) or text; the response is scored on
the 0-4 three-trait rubric and stored in `speaking_attempt`. This is separate from
the free-form `/speak` conversation, which is left unchanged.
"""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tutor.bot.conversation import _say, download_voice
from tutor.eval.schemas import SpeakingTaskPayload
from tutor.eval.speaking import (
    TASK_LABELS,
    TIMINGS,
    evaluate_speaking,
    generate_speaking_task,
)
from tutor.factory import Services

# Per-user background timer tasks (prep-over / time's-up nudges). Kept out of FSM
# state because asyncio.Task is not serializable.
_timers: dict[int, list[asyncio.Task[Any]]] = {}


class SpeakingState(StatesGroup):
    active = State()


def _cancel_timers(user_id: int) -> None:
    for task in _timers.pop(user_id, []):
        task.cancel()


def _schedule(user_id: int, coro: Any) -> None:
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:  # no running loop (e.g. unit tests) — skip timers
        return
    _timers.setdefault(user_id, []).append(task)


async def _nudge(svc: Services, user_id: int, delay: float, text: str) -> None:
    try:
        await asyncio.sleep(delay)
        await svc.notifier.send(user_id, text)
    except asyncio.CancelledError:  # the learner finished early
        pass


async def start_speaking_task(
    svc: Services, bot: Any, user_id: int, state: FSMContext, task_type: str
) -> None:
    """Generate a TOEFL speaking task, deliver it, and start the timers."""
    await svc.notifier.send(user_id, "🎤 Preparing your task…")
    try:
        task = await generate_speaking_task(svc.llm, task_type)
    except Exception:  # noqa: BLE001
        await svc.notifier.send(user_id, "Couldn't generate a task. Try again later.")
        return

    label = TASK_LABELS.get(task.task_type, task.task_type)
    prep_sec, resp_sec = TIMINGS.get(task.task_type, (15, 45))

    await svc.notifier.send(user_id, f"🎙 <b>TOEFL Speaking — {label}</b>")
    if task.reading:
        await svc.notifier.send(user_id, f"<b>Read:</b>\n{task.reading}")
    if task.listening:
        # Read the listening part aloud (best-effort TTS), like the real exam.
        await _say(svc, bot, user_id, f"🎧 <b>Listen:</b>\n{task.listening}")
    await svc.notifier.send(
        user_id,
        f"<b>Question:</b>\n{task.prompt}\n\n"
        f"⏳ Preparation: <b>{prep_sec}s</b>. Then speak for <b>{resp_sec}s</b>.\n"
        "Answer by voice (or type) when prompted. Send /stop to cancel.",
    )

    await state.set_state(SpeakingState.active)
    await state.update_data(task=task.model_dump(), phase="prep")

    _cancel_timers(user_id)
    _schedule(
        user_id,
        _nudge(
            svc,
            user_id,
            prep_sec,
            f"🎙 <b>Speak now!</b> You have ~{resp_sec}s. "
            "Send a voice message (or type your answer).",
        ),
    )
    _schedule(
        user_id,
        _nudge(
            svc,
            user_id,
            prep_sec + resp_sec,
            "⏱ <b>Time's up!</b> Send your recording now to get it scored.",
        ),
    )


async def handle_response(
    svc: Services, bot: Any, user_id: int, state: FSMContext, transcript: str
) -> None:
    """Score a transcribed (or typed) spoken response and store it."""
    _cancel_timers(user_id)
    data = await state.get_data()
    task_data = data.get("task")
    await state.clear()
    if not task_data:
        return
    task = SpeakingTaskPayload(**task_data)

    if len(transcript.strip()) < 5:
        await svc.notifier.send(
            user_id, "That response was too short to score. Use /speaking to try again."
        )
        return

    await svc.notifier.send(user_id, "⏳ Scoring your response…")
    try:
        ev = await evaluate_speaking(svc.llm, task, transcript)
    except Exception as exc:  # noqa: BLE001
        await svc.notifier.send(user_id, f"Couldn't score that: {str(exc)[:100]}.")
        return

    feedback_summary = (
        f"Overall {ev.score}/4 (~{ev.scaled_30}/30) · "
        f"delivery {ev.delivery}/4, language {ev.language_use}/4, "
        f"development {ev.topic_development}/4\n{ev.feedback}"
    )
    svc.repo.save_speaking_attempt(
        user_id,
        task.task_type,
        task.prompt,
        transcript,
        delivery=ev.delivery,
        language_use=ev.language_use,
        topic_dev=ev.topic_development,
        score=ev.score,
        scaled_30=ev.scaled_30,
        feedback=feedback_summary,
    )

    parts = [
        f"🎙 <b>Speaking score: {ev.score}/4</b> (~{ev.scaled_30}/30 scaled)\n",
        f"• Delivery: <b>{ev.delivery}/4</b>",
        f"• Language use: <b>{ev.language_use}/4</b>",
        f"• Topic development: <b>{ev.topic_development}/4</b>",
    ]
    if ev.strengths:
        parts.append("\n<b>Strengths:</b>")
        parts += [f"  ✅ {s}" for s in ev.strengths]
    if ev.improvements:
        parts.append("\n<b>To improve:</b>")
        parts += [f"  ⚠️ {s}" for s in ev.improvements]
    if ev.feedback:
        parts.append(f"\n{ev.feedback}")
    await svc.notifier.send(user_id, "\n".join(parts))


async def handle_voice_response(
    svc: Services, bot: Any, user_id: int, state: FSMContext, message: Any
) -> None:
    """Transcribe a voice response then score it."""
    transcript = await download_voice(bot, svc, message)
    await svc.notifier.send(user_id, f"📝 <i>{transcript}</i>")
    await handle_response(svc, bot, user_id, state, transcript)


def cancel_speaking(user_id: int) -> None:
    """Cancel any pending timers (called on /stop)."""
    _cancel_timers(user_id)


__all__ = [
    "SpeakingState",
    "start_speaking_task",
    "handle_response",
    "handle_voice_response",
    "cancel_speaking",
]
