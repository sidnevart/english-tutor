"""Telegram-independent rendering for daily plans and task prompts."""

from __future__ import annotations

import html

from tutor.interfaces.notifier import Keyboard
from tutor.practice.models import Section, TaskType
from tutor.practice.planner import DailyPlan, PlanEntry

TASK_LABELS = {
    TaskType.COMPLETE_WORDS: "Complete the Words",
    TaskType.DAILY_LIFE: "Read in Daily Life",
    TaskType.ACADEMIC_PASSAGE: "Academic Passage",
    TaskType.LISTEN_REPEAT: "Listen and Repeat",
    TaskType.INTERVIEW: "Take an Interview",
    TaskType.BUILD_SENTENCE: "Build a Sentence",
    TaskType.EMAIL: "Write an Email",
    TaskType.ACADEMIC_DISCUSSION: "Academic Discussion",
}

SECTION_LABELS = {
    Section.READING: "📖 Reading",
    Section.SPEAKING: "🎙 Speaking",
    Section.WRITING: "✍️ Writing",
}

STATUS_LABELS = {"not_started": "not started", "in_progress": "in progress", "complete": "complete"}


def _h(value: object) -> str:
    return html.escape(str(value))


def render_plan(plan: DailyPlan) -> tuple[str, Keyboard]:
    lines = [f"<b>TOEFL plan · {plan.local_date:%d.%m.%Y}</b>", ""]
    keyboard: Keyboard = []
    for entry in plan.entries:
        lines.append(
            f"{SECTION_LABELS[entry.section]} — {TASK_LABELS[entry.task_type]} · "
            f"<b>{STATUS_LABELS.get(entry.status, entry.status)}</b>"
        )
        if entry.status != "complete":
            keyboard.append([(f"Start {entry.section.value.title()}", f"practice:{entry.id}")])
    if not keyboard:
        lines.extend(["", "✅ Today's plan is complete."])
    return "\n".join(lines), keyboard


def render_prompt(entry: PlanEntry, item_index: int = 0) -> str:
    payload = entry.payload
    kind = entry.task_type
    title = f"<b>{TASK_LABELS[kind]}</b>"
    if kind is TaskType.COMPLETE_WORDS:
        return f"{title}\n\n{_h(payload['passage'])}\n\nReply with all 10 endings in order."
    if kind in {TaskType.DAILY_LIFE, TaskType.ACADEMIC_PASSAGE}:
        question = payload["questions"][item_index]
        options = "\n".join(f"{i + 1}. {_h(text)}" for i, text in enumerate(question["options"]))
        passage = f"{_h(payload['passage'])}\n\n" if item_index == 0 else ""
        return (
            f"{title}\n\n{passage}<b>Question {item_index + 1}</b>\n"
            f"{_h(question['stem'])}\n{options}"
        )
    if kind is TaskType.LISTEN_REPEAT:
        return (
            f"{title}\n\nSentence {item_index + 1}/7. Listen without speaking. "
            "After the beep, repeat once in one voice message. TOEFL allows "
            "about 8–12 seconds for the response."
        )
    if kind is TaskType.INTERVIEW:
        return (
            f"{title}\n\n{_h(payload['scenario'])}\n\nQuestion {item_index + 1}/4. "
            "You have 45 seconds and no preparation time."
        )
    if kind is TaskType.BUILD_SENTENCE:
        fragments = " · ".join(_h(value) for value in payload["items"][item_index]["fragments"])
        return f"{title}\n\nItem {item_index + 1}/10\n{fragments}\n\nSend the complete sentence."
    if kind is TaskType.EMAIL:
        points = "\n".join(f"• {_h(point)}" for point in payload["required_points"])
        return (
            f"{title} · 7 minutes\n\n{_h(payload['scenario'])}\n"
            f"Audience: {_h(payload['audience'])}\nPurpose: {_h(payload['purpose'])}\n"
            f"Include:\n{points}\n\n"
            "Your first text submission is final."
        )
    return (
        f"{title} · 10 minutes\n\nProfessor: {_h(payload['professor'])}\n\n"
        f"{_h(payload['student_a'])}\n\n{_h(payload['student_b'])}\n\n"
        "Write your contribution. Your first text submission is final."
    )
