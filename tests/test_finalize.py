"""finalize_review derives the score from recorded attempts and is idempotent."""

from __future__ import annotations

from tutor.app import open_services
from tutor.config import Settings
from tutor.domain.enums import ContentType, DeliveryStatus, SourceType
from tutor.domain.models import RawItem
from tutor.pipeline import build_evaluation, deliver_new, finalize_review


async def test_finalize_from_incremental_attempts(tmp_path):
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "t.db"),
        data_dir=str(tmp_path / "data"),
        llm_backend="stub",
        notifier_backend="stub",
        anki_backend="genanki",
        soul_dir=str(tmp_path / "soul"),
    )
    with open_services(settings) as svc:
        user = settings.admin_user_id
        cid = svc.repo.add_content(
            RawItem(
                source_type=SourceType.CHANNEL,
                source_ref="1",
                external_id="e",
                content_type=ContentType.ARTICLE,
                title="t",
                body_text="A passage about ephemeral serendipitous quotidian discoveries.",
            ),
            user,
        )
        await deliver_new(svc, user, 1)
        quiz = await build_evaluation(svc, cid, user)

        # record answers one at a time (interactive style): all correct
        for q in quiz.questions:
            svc.repo.record_attempt(q.id, user, q.correct_index, True)

        result = await finalize_review(svc, cid, user)
        assert result.correct == len(quiz.questions)
        assert result.anki.apkg_path is not None
        assert svc.repo.get(cid).status == DeliveryStatus.REVIEWED

        # idempotent: a second finalize does not raise or re-transition
        again = await finalize_review(svc, cid, user)
        assert again.correct == len(quiz.questions)
        assert svc.repo.get(cid).status == DeliveryStatus.REVIEWED
