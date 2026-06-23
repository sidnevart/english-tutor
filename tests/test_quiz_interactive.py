"""Interactive in-chat quiz flow: single-select run + multi-select summary."""

from __future__ import annotations

from tutor.app import open_services
from tutor.bot.quiz import handle_option, handle_submit, start_quiz
from tutor.config import Settings
from tutor.domain.enums import ContentType, DeliveryStatus, QuizKind, SourceType
from tutor.domain.models import QuizQuestion, RawItem
from tutor.pipeline import deliver_new

ARTICLE = (
    "Researchers describe a serendipitous discovery: an ephemeral compound with "
    "ubiquitous applications and profound implications for sustainable energy."
)


class FakeState:
    def __init__(self) -> None:
        self._data: dict = {}
        self._state = None

    async def set_state(self, state) -> None:  # noqa: ANN001
        self._state = state

    async def get_data(self) -> dict:
        return dict(self._data)

    async def update_data(self, **kwargs) -> None:
        self._data.update(kwargs)

    async def clear(self) -> None:
        self._data = {}
        self._state = None


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


def _add_article(svc, user) -> int:  # noqa: ANN001
    cid = svc.repo.add_content(
        RawItem(
            source_type=SourceType.CHANNEL,
            source_ref="1137165265",
            external_id="post-1",
            content_type=ContentType.ARTICLE,
            title="A discovery",
            body_text=ARTICLE,
        ),
        user_id=user,
    )
    assert cid is not None
    return cid


async def test_single_select_quiz_full_run(tmp_path):
    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id
        cid = _add_article(svc, user)
        await deliver_new(svc, user, limit=1)

        state = FakeState()
        await start_quiz(svc, None, user, state, cid)

        quiz = svc.repo.get_quiz_auto(cid)
        assert quiz is not None and quiz.questions
        # Answer every question correctly, one option tap at a time.
        for q in quiz.questions:
            await handle_option(svc, None, user, state, q.correct_index)

        # All answered -> graded, reviewed, attempts recorded.
        assert svc.repo.get(cid).status == DeliveryStatus.REVIEWED
        attempts = svc.repo.attempts_for_content(cid, user)
        assert len(attempts) == len(quiz.questions)
        assert all(a.is_correct for a in attempts)


async def test_multi_select_summary_quiz(tmp_path):
    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id
        cid = _add_article(svc, user)
        await deliver_new(svc, user, limit=1)

        # Pre-seed a quiz with a single multi-select (summary) question so
        # start_quiz uses it instead of generating a new one.
        summary = QuizQuestion(
            prompt="Choose the 3 statements that best summarize the passage.",
            options=["a", "b", "c", "d", "e", "f"],
            correct_index=0,
            correct_indices=[0, 2, 4],
            question_type="summary",
        )
        svc.repo.save_quiz(cid, QuizKind.READING, [summary])

        state = FakeState()
        await start_quiz(svc, None, user, state, cid)

        # Toggle the three correct options, then submit.
        for i in (0, 2, 4):
            await handle_option(svc, None, user, state, i)
        await handle_submit(svc, None, user, state)

        assert svc.repo.get(cid).status == DeliveryStatus.REVIEWED
        attempts = svc.repo.attempts_for_content(cid, user)
        assert len(attempts) == 1
        assert attempts[0].is_correct is True


async def test_multi_select_wrong_set_is_incorrect(tmp_path):
    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id
        cid = _add_article(svc, user)
        await deliver_new(svc, user, limit=1)
        summary = QuizQuestion(
            prompt="Choose 3.",
            options=["a", "b", "c", "d", "e", "f"],
            correct_index=0,
            correct_indices=[0, 2, 4],
        )
        svc.repo.save_quiz(cid, QuizKind.READING, [summary])

        state = FakeState()
        await start_quiz(svc, None, user, state, cid)
        for i in (0, 2, 5):  # one wrong
            await handle_option(svc, None, user, state, i)
        await handle_submit(svc, None, user, state)

        attempts = svc.repo.attempts_for_content(cid, user)
        assert len(attempts) == 1
        assert attempts[0].is_correct is False