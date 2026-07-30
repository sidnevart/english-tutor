from __future__ import annotations

from datetime import date

from conftest import TEST_USER

from tutor.bot.handlers import COMMANDS, HELP_TEXT
from tutor.bot.views import render_plan, render_prompt
from tutor.catalog import BundledCatalog
from tutor.practice.models import Section, TaskType
from tutor.practice.planner import DailyPlanner


def test_only_focused_toefl_commands_remain() -> None:
    slugs = {slug for slug, _ in COMMANDS}
    assert slugs == {
        "start",
        "today",
        "reading",
        "speaking",
        "writing",
        "progress",
        "export",
        "cancel",
        "help",
        "reset",
    }
    assert "/speak —" not in HELP_TEXT
    assert "/coach" not in HELP_TEXT
    assert "Anki" not in HELP_TEXT


def test_plan_and_all_task_prompts_render(repo) -> None:
    planner = DailyPlanner(repo, BundledCatalog.load())
    plans = [planner.ensure_plan(TEST_USER, date(2026, 7, 30 + offset)) for offset in range(2)]
    # Use a wider rotation from separate dates that remain within July/August.
    plans = [planner.ensure_plan(TEST_USER, date(2026, 7, 30))]
    from datetime import timedelta

    plans = [
        planner.ensure_plan(TEST_USER, date(2026, 7, 30) + timedelta(days=i)) for i in range(6)
    ]
    text, keyboard = render_plan(plans[0])
    assert "TOEFL plan" in text and len(keyboard) == 3

    entries = [entry for plan in plans for entry in plan.entries]
    assert {entry.task_type for entry in entries} == set(TaskType)
    for entry in entries:
        prompt = render_prompt(entry)
        assert prompt and entry.section in {Section.READING, Section.SPEAKING, Section.WRITING}
