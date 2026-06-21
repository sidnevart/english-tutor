"""Multi-turn conversation engine for speaking practice and content dialog.

Sessions live in aiogram's in-memory FSM. A turn is the transcript-in-`user`
pattern over the existing `LLMClient.complete(system, user)` — no interface
change, never on the graded path. Bot replies are text plus an optional TTS
voice note (Groq Orpheus); a TTS failure degrades to text only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from tutor.factory import Services
from tutor.memory import Memory

_MAX_TURNS = 12  # keep the last N exchanges to bound the prompt


class ConversationState(StatesGroup):
    active = State()


def _speak_instructions() -> str:
    return (
        "Run a short spoken English practice. Have a natural back-and-forth: react "
        "to what the learner says, ask ONE follow-up question at a time, and gently "
        "correct only major errors inline. Keep replies to 2-4 sentences."
    )


def _discuss_instructions(body_text: str) -> str:
    excerpt = body_text.strip()[:1500]
    return (
        "Discuss the passage below with the learner for listening/speaking practice. "
        "Ask open comprehension and opinion questions, ONE at a time, react to their "
        "answers, and gently correct major errors. Keep replies to 2-4 sentences.\n\n"
        f"PASSAGE:\n{excerpt}"
    )


def _system(svc: Services, user_id: int, mode: str, body_text: str = "") -> str:
    persona = Memory(svc.settings.soul_dir, user_id).persona()
    instr = _discuss_instructions(body_text) if mode == "discuss" else _speak_instructions()
    return f"{persona}\n\n{instr}"


def _transcript(history: list[dict[str, str]], prompt_next: bool = True) -> str:
    lines = [f"{'Coach' if h['role'] == 'coach' else 'Learner'}: {h['content']}" for h in history]
    if prompt_next:
        lines.append("Coach:")
    return "\n".join(lines)


async def _say(svc: Services, bot: Any, user_id: int, text: str) -> None:
    """Send text, and (if a real TTS backend is set) a voice note too."""
    await svc.notifier.send(user_id, text)
    if not svc.settings.voice_enabled or bot is None:
        return
    try:
        from aiogram.types import FSInputFile

        out = Path(svc.settings.data_path) / f"tts_{user_id}.ogg"
        path = await svc.synthesizer.synthesize(text, out)
        await bot.send_voice(user_id, FSInputFile(str(path)))
    except Exception:  # noqa: BLE001 — text already delivered; voice is best-effort
        pass


async def download_voice(bot: Any, svc: Services, message: Any) -> str:
    """Download a Telegram voice message and transcribe it."""
    dest = Path(svc.settings.data_path) / f"voice_{message.voice.file_unique_id}.oga"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tg_file = await bot.get_file(message.voice.file_id)
    await bot.download_file(tg_file.file_path, destination=dest)
    text = await svc.transcriber.transcribe(dest)
    dest.unlink(missing_ok=True)
    return text


async def start_speaking(svc: Services, bot: Any, user_id: int, state: FSMContext) -> None:
    system = _system(svc, user_id, "speak")
    task = await svc.llm.complete(
        system
        + "\n\nGive the learner ONE short TOEFL-style speaking task to begin (1-2 sentences).",
        "Begin the practice.",
    )
    await state.set_state(ConversationState.active)
    await state.update_data(
        mode="speak", content_id=None, history=[{"role": "coach", "content": task}]
    )
    await _say(
        svc,
        bot,
        user_id,
        "🎙 <b>Speaking practice</b> — answer by voice or text. Send /stop to finish.\n\n" + task,
    )


async def start_discussion(
    svc: Services, bot: Any, user_id: int, state: FSMContext, content_id: int
) -> None:
    content = svc.repo.get(content_id)
    if content is None or not content.body_text.strip():
        await svc.notifier.send(user_id, "That material isn't ready to discuss yet.")
        return
    system = _system(svc, user_id, "discuss", content.body_text)
    opener = await svc.llm.complete(
        system + "\n\nOpen the discussion with ONE engaging question about the passage.",
        "Begin the discussion.",
    )
    await state.set_state(ConversationState.active)
    await state.update_data(
        mode="discuss", content_id=content_id, history=[{"role": "coach", "content": opener}]
    )
    title = content.title or "today's material"
    await _say(
        svc,
        bot,
        user_id,
        f"💬 <b>Let's discuss: {title}</b> — reply by voice or text. Send /stop to finish.\n\n"
        + opener,
    )


async def handle_turn(
    svc: Services, bot: Any, user_id: int, state: FSMContext, user_text: str
) -> None:
    data = await state.get_data()
    mode = data.get("mode", "speak")
    content_id = data.get("content_id")
    history = list(data.get("history", []))
    history.append({"role": "learner", "content": user_text})

    body_text = ""
    if content_id:
        content = svc.repo.get(content_id)
        body_text = content.body_text if content else ""
    system = _system(svc, user_id, mode, body_text)
    reply = await svc.llm.complete(system, _transcript(history))

    history.append({"role": "coach", "content": reply})
    await state.update_data(history=history[-_MAX_TURNS * 2 :])
    await _say(svc, bot, user_id, reply)


async def end_session(svc: Services, user_id: int, state: FSMContext) -> None:
    data = await state.get_data()
    history = list(data.get("history", []))
    await state.clear()
    if len(history) < 2:
        await svc.notifier.send(user_id, "Practice ended. 👋")
        return
    system = Memory(svc.settings.soul_dir, user_id).persona() + (
        "\n\nThe practice session is over. Give brief, encouraging feedback on the "
        "learner's English from this conversation: 1-2 strengths and up to 3 specific "
        "corrections (grammar / vocabulary / phrasing). Keep it short."
    )
    feedback = await svc.llm.complete(system, _transcript(history, prompt_next=False))
    await svc.notifier.send(user_id, "✅ <b>Practice complete!</b>\n\n" + feedback)
