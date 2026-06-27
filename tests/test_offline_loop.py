"""The whole loop, end to end, on stubs only — no network, no secrets.

deliver -> daily TOEFL file (builds quiz + vocab) -> fill in -> grade ->
reviewed + Anki, asserting the state machine and the produced artifacts.
"""

from __future__ import annotations

import re

from tutor.adapters.notify.stub import StubNotifier
from tutor.app import open_services
from tutor.config import Settings
from tutor.domain.enums import ContentType, DeliveryStatus, SourceType
from tutor.domain.models import RawItem
from tutor.pipeline import deliver_new
from tutor.worksheet.daily_file import (
    daily_from_json,
    grade_daily,
    render_daily_md,
    send_daily_file,
)

ARTICLE = (
    "Researchers describe a seripitous discovery: an ephemeral compound "
    "with ubiquitous applications. The quotidian work of the lab belies its "
    "profound implications for sustainable energy. The findings could reshape "
    "how industry approaches catalysis, renewable storage, and emissions."
)

_LETTERS = "ABCDEFGH"


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "tutor.db"),
        data_dir=str(tmp_path / "data"),
        llm_backend="stub",
        notifier_backend="stub",
        anki_backend="genanki",
        soul_dir=str(tmp_path / "soul"),
    )


async def test_full_loop_offline(tmp_path):
    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id

        cid = svc.repo.add_content(
            RawItem(
                source_type=SourceType.CHANNEL,
                source_ref="1137165265",
                external_id="post-42",
                content_type=ContentType.ARTICLE,
                title="A serendipitous discovery",
                body_text=ARTICLE,
            ),
            user_id=user,
        )
        assert cid is not None

        # 1) Morning delivery: a card + Anki deck, NO per-item task file.
        delivered = await deliver_new(svc, user, limit=5)
        assert delivered == [cid]
        assert svc.repo.get(cid).status == DeliveryStatus.DELIVERED
        notifier: StubNotifier = svc.notifier  # type: ignore[assignment]
        assert len(notifier.messages) == 1
        assert notifier.messages[0].keyboard is None
        # No per-item task file anymore (consolidated into the daily file).
        task_files = [f for f in notifier.files if f.caption and "task" in f.caption.lower()]
        assert len(task_files) == 0

        # 2) Build + send the daily TOEFL file (builds & saves the quiz + vocab).
        assert await send_daily_file(svc, user, [cid])
        quiz = svc.repo.get_quiz_auto(cid)
        assert quiz is not None
        assert len(quiz.questions) >= 1
        assert len(svc.repo.get_vocab(cid)) > 0
        daily_files = [f for f in notifier.files if f.caption and "Daily TOEFL" in f.caption]
        assert len(daily_files) == 1

        # 3) Fill in all-correct answers and grade the daily file.
        ws = svc.repo.get_latest_worksheet(user, status="pending")
        assert ws is not None
        payload = daily_from_json(ws["items_json"])
        md = render_daily_md(payload, ws["id"])

        correct: list[str] = []
        for block in payload.reading:
            correct += [_LETTERS[q.correct_index] for q in block.questions]
        for block in payload.listening:
            correct += [_LETTERS[q.correct_index] for q in block.questions]
        correct += [_LETTERS[q.correct_index] for q in payload.fill_blanks]
        correct += ["A" for _ in payload.collocation_match]  # correct partner is first

        it = iter(correct)

        def _fill(_m: object) -> str:
            return next(it, "____")

        filled = re.sub(r"____", _fill, md)
        score, feedback = await grade_daily(svc, user, payload, filled)

        # 4) Reviewed + attempts recorded + Anki deck for missed (none missed here).
        assert svc.repo.get(cid).status == DeliveryStatus.REVIEWED
        assert 0.0 <= score <= 1.0
        assert "Daily TOEFL Results" in feedback
        attempts = svc.repo.attempts_for_content(cid, user)
        assert len(attempts) == len(quiz.questions)
        assert all(a.is_correct for a in attempts)

        # 5) Missed-cards Anki deck is delivered by the grader.
        anki_files = [f for f in notifier.files if f.caption and "🎴" in f.caption]
        assert len(anki_files) >= 1
