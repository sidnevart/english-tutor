"""File-based TOEFL Writing: task file generation, parsing, and grading."""

from __future__ import annotations

from tutor.app import open_services
from tutor.bot.writing import (
    _ESSAY_HEADING,
    grade_essay_file,
    render_writing_task_md,
    start_writing_task,
)
from tutor.config import Settings


class _User:
    def __init__(self, uid: int) -> None:
        self.id = uid


class FakeMessage:
    def __init__(self, uid: int) -> None:
        self.from_user = _User(uid)
        self.answers: list[str] = []

    async def answer(self, text: str, **_: object) -> None:
        self.answers.append(text)


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "tutor.db"),
        data_dir=str(tmp_path / "data"),
        llm_backend="stub",
        notifier_backend="stub",
        anki_backend="null",
        soul_dir=str(tmp_path / "soul"),
    )


def test_render_writing_task_embeds_marker_and_answer_area():
    md = render_writing_task_md(42, "independent", "Do you agree or disagree?")
    assert "<!-- ESSAY_TASK_ID: 42 -->" in md
    assert _ESSAY_HEADING in md
    assert "Do you agree or disagree?" in md


def test_render_integrated_includes_passage_not_lecture():
    md = render_writing_task_md(
        7, "integrated", "Summarize the lecture.", passage="READING", lecture="LECTURE"
    )
    assert "READING" in md
    assert "LECTURE" not in md  # lecture is audio-only, never in the file


async def test_start_and_grade_writing_task(tmp_path):
    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id
        svc.repo.ensure_subscriber(user)

        # 1) /write generates a task file (independent under the stub LLM).
        await start_writing_task(svc, None, user)
        files = [f for f in svc.notifier.files if f.caption and "Writing task" in f.caption]
        assert len(files) == 1
        md = files[0].path.read_text(encoding="utf-8")
        assert "<!-- ESSAY_TASK_ID:" in md

        # 2) Fill in an essay and send the file back.
        essay = ("Technology has changed how we communicate in profound ways. " * 8).strip()
        filled = md + "\n" + essay + "\n"
        import re

        m = re.search(r"<!--\s*ESSAY_TASK_ID:\s*(\d+)\s*-->", md)
        task_id = int(m.group(1))
        msg = FakeMessage(user)
        await grade_essay_file(svc, msg, task_id, filled)

        # 3) Essay saved + writing task marked submitted.
        assert svc.repo.essay_count(user) == 1
        task = svc.repo.get_writing_task(task_id)
        assert task["status"] == "submitted"
        assert any("Essay Score" in a for a in msg.answers)
