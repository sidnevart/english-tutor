"""The whole loop, end to end, on stubs only — no network, no secrets.

deliver -> build evaluation -> grade -> review -> .apkg, asserting the state
machine and the produced artifacts at each step.
"""

from __future__ import annotations

from tutor.adapters.notify.stub import StubNotifier
from tutor.app import open_services
from tutor.config import Settings
from tutor.domain.enums import ContentType, DeliveryStatus, SourceType
from tutor.domain.models import RawItem
from tutor.pipeline import build_evaluation, deliver_new, submit_answers

ARTICLE = (
    "Researchers describe a serendipitous discovery: an ephemeral compound "
    "with ubiquitous applications. The quotidian work of the lab belies its "
    "profound implications for sustainable energy."
)


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

        # 1) Morning delivery
        delivered = await deliver_new(svc, user, limit=5)
        assert delivered == [cid]
        assert svc.repo.get(cid).status == DeliveryStatus.DELIVERED
        notifier: StubNotifier = svc.notifier  # type: ignore[assignment]
        assert len(notifier.messages) == 1
        assert notifier.messages[0].keyboard == [[("📖 Quiz me", f"quiz:{cid}")]]

        # 2) Evening evaluation (vocab deterministic + quiz via stub LLM)
        quiz = await build_evaluation(svc, cid, user)
        assert len(quiz.questions) == 3
        assert len(svc.repo.get_vocab(cid)) > 0

        # 3) Answer: all correct except the first question
        answers = {q.id: q.correct_index for q in quiz.questions}
        first = quiz.questions[0]
        answers[first.id] = (first.correct_index + 1) % len(first.options)

        result = await submit_answers(svc, cid, user, answers)
        assert result.total == 3
        assert result.correct == 2

        # 4) Reviewed + Anki artifact + learner notified with the deck file
        assert svc.repo.get(cid).status == DeliveryStatus.REVIEWED
        assert result.anki.apkg_path is not None
        from pathlib import Path

        assert Path(result.anki.apkg_path).exists()
        assert len(notifier.files) == 1
        assert notifier.files[0].caption.startswith("🎴")

        # attempts persisted: exactly one wrong
        attempts = svc.repo.attempts_for_content(cid, user)
        assert sum(1 for a in attempts if not a.is_correct) == 1
