"""File-based TOEFL Writing: a task file the learner fills in and sends back.

`/write` generates a TOEFL writing prompt, renders it to a Markdown file with
an answer area (and, for integrated tasks, sends the lecture as audio-only — no
transcript, mirroring the real exam), and saves a pending `writing_task` row.
The learner writes the essay in the file and sends it back later; `on_document`
routes it by the `ESSAY_TASK_ID` marker to `grade_essay_file`, which scores it
with the official 0-5 rubric (`evaluate_essay`) and stores it in the `essay` table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiogram.types import Message

from tutor.bot.conversation import _say_audio_only
from tutor.eval.essay import evaluate_essay, generate_essay_prompt, next_essay_type
from tutor.factory import Services

_ESSAY_HEADING = "## Your essay (write below)"


def render_writing_task_md(
    task_id: int, essay_type: str, prompt: str, passage: str = "", lecture: str = ""
) -> str:
    """Render the writing-task file the learner fills in and sends back."""
    parts: list[str] = [
        f"# ✍️ TOEFL Writing — {essay_type.title()}",
        f"<!-- ESSAY_TASK_ID: {task_id} -->",
        "",
        f"**Type:** {essay_type}",
        "",
        "## Task",
        prompt,
        "",
    ]
    if passage:
        parts += ["## Reading passage", passage, ""]
    if lecture:
        parts += [
            "*Listen to the attached audio (the lecture), then write your response. "
            "The lecture transcript is NOT shown — just like the real exam.*",
            "",
        ]
    parts += [
        "Write your essay (aim for 300+ words for independent / 150-225 for integrated) "
        "in the section below, then send this file back to the bot for grading.",
        "",
        "---",
        "",
        _ESSAY_HEADING,
        "",
        "<!-- write your essay after this line -->",
        "",
    ]
    return "\n".join(parts)


def _extract_essay(text: str) -> str:
    """Pull the learner's essay out of a returned writing-task file."""
    idx = text.find(_ESSAY_HEADING)
    if idx == -1:
        return text  # whole file as a fallback
    body = text[idx + len(_ESSAY_HEADING) :]
    # Drop an optional HTML comment hint line right after the heading.
    body = body.lstrip("\n")
    if body.lstrip().startswith("<!--"):
        nl = body.find("\n")
        body = body[nl + 1 :] if nl != -1 else ""
    return body.strip()


async def start_writing_task(svc: Services, bot: Any, user_id: int) -> None:
    """Generate a TOEFL writing task, save it, and send the task file (+ audio)."""
    last_type = svc.repo.last_essay_type(user_id)
    essay_type = next_essay_type(last_type)

    try:
        prompt_data = await generate_essay_prompt(svc.llm, essay_type)
    except Exception:  # noqa: BLE001
        await svc.notifier.send(user_id, "Couldn't generate a writing task. Try again later.")
        return

    prompt = prompt_data["prompt"]
    passage = prompt_data.get("passage", "")
    lecture = prompt_data.get("lecture", "")
    task_id = svc.repo.save_writing_task(user_id, essay_type, prompt, passage, lecture)

    md = render_writing_task_md(task_id, essay_type, prompt, passage, lecture)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    md_path = Path(svc.settings.data_path) / f"writing_task_{date_str}_{task_id}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")

    await svc.notifier.send(
        user_id,
        f"✍️ <b>TOEFL Writing — {essay_type.title()}</b>\n"
        f"Task file sent below. Write your essay in it and send the file back "
        f"whenever you're ready (not necessarily today) — I'll grade it 0-5.",
    )
    await svc.notifier.send_file(user_id, md_path, caption=f"✍️ Writing task — {essay_type}")

    # Integrated task: deliver the lecture as audio-only (no transcript).
    if lecture:
        await _say_audio_only(
            svc, bot, user_id, lecture, caption="🎧 Listen to the lecture, then write"
        )


async def grade_essay_file(svc: Services, message: Message, task_id: int, text: str) -> None:
    """Grade an essay submitted as a writing-task file."""
    user_id = message.from_user.id
    task = svc.repo.get_writing_task(task_id)
    if task is None or task["user_id"] != user_id:
        await message.answer("⚠️ Writing task not found — it may have expired.")
        return

    essay_text = _extract_essay(text)
    if len(essay_text.strip()) < 50:
        await message.answer(
            "Your essay is too short for meaningful feedback. "
            "Try to write at least 100 words and send the file again."
        )
        return

    await message.answer("⏳ Evaluating your essay...")
    essay_type = task["essay_type"]
    prompt = task["prompt"]
    passage = task["passage"]
    lecture = task["lecture"]

    try:
        ev = await evaluate_essay(
            svc.llm, prompt, essay_text, essay_type, passage=passage, lecture=lecture
        )
    except Exception as exc:  # noqa: BLE001
        await message.answer(f"Couldn't evaluate your essay: {str(exc)[:100]}. Try again later.")
        return

    corrections_text = (
        "\n".join(f"- {c.error} → {c.correction}" for c in ev.corrections) if ev.corrections else ""
    )
    feedback_summary = (
        f"Score: {ev.score}/5 (~{ev.scaled_30}/30)\n"
        f"Strengths: {', '.join(ev.strengths)}\n"
        f"Weaknesses: {', '.join(ev.weaknesses)}\n"
        f"Corrections:\n{corrections_text}\n"
        f"Suggestions: {', '.join(ev.suggestions)}"
    )
    svc.repo.save_essay(user_id, prompt, essay_text, ev.score, feedback_summary, essay_type)
    svc.repo.mark_writing_task_submitted(task_id)
    if ev.corrections:
        svc.repo.save_session_errors(
            user_id,
            f"essay:{essay_type}",
            [
                {
                    "type": c.type,
                    "error": c.error,
                    "correction": c.correction,
                    "context": prompt[:100],
                }
                for c in ev.corrections
            ],
        )

    score_emoji = {5: "🎉", 4: "👍", 3: "📝", 2: "📚", 1: "💪", 0: "💪"}.get(ev.score, "📝")
    parts = [
        f"{score_emoji} <b>Essay Score: {ev.score}/5</b> (~{ev.scaled_30}/30 scaled)\n",
    ]
    if ev.strengths:
        parts.append("<b>Strengths:</b>")
        parts += [f"  ✅ {s}" for s in ev.strengths]
    if ev.weaknesses:
        parts.append("\n<b>Areas to improve:</b>")
        parts += [f"  ⚠️ {w}" for w in ev.weaknesses]
    if ev.corrections:
        parts.append(f"\n<b>Corrections ({len(ev.corrections)}):</b>")
        for c in ev.corrections[:5]:
            parts.append(f"  ❌ <i>{c.error}</i> → <b>{c.correction}</b>")
        if len(ev.corrections) > 5:
            parts.append(f"  ... and {len(ev.corrections) - 5} more")
    if ev.suggestions:
        parts.append("\n<b>Suggestions:</b>")
        parts += [f"  💡 {s}" for s in ev.suggestions]
    await message.answer("\n".join(parts))


__all__ = ["start_writing_task", "grade_essay_file", "render_writing_task_md"]
