"""TOEFL Speaking: task generation, rubric scoring, and the scoring flow."""

from __future__ import annotations

from tutor.adapters.llm.stub import StubLLMClient
from tutor.app import open_services
from tutor.config import Settings
from tutor.eval.schemas import SpeakingTaskPayload
from tutor.eval.speaking import (
    TASK_TYPES,
    TIMINGS,
    evaluate_speaking,
    generate_speaking_task,
    next_task_type,
)


class FakeState:
    """Minimal stand-in for aiogram's FSMContext (dict-backed)."""

    def __init__(self, data: dict | None = None) -> None:
        self._data = dict(data or {})
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


def test_task_rotation_and_timings():
    assert next_task_type(None) == "independent"
    assert next_task_type("independent") == "campus"
    assert next_task_type("lecture") == "independent"  # wraps
    # Every task type has a (prep, response) timing.
    for t in TASK_TYPES:
        prep, resp = TIMINGS[t]
        assert prep > 0 and resp > 0


async def test_generate_task_normalizes_type():
    task = await generate_speaking_task(StubLLMClient(), "campus")
    # The stub returns a non-canonical task_type, which must be normalized back.
    assert task.task_type == "campus"
    assert task.prompt


async def test_evaluate_speaking_returns_rubric():
    task = SpeakingTaskPayload(task_type="independent", prompt="Do you prefer X or Y?")
    ev = await evaluate_speaking(StubLLMClient(), task, "I prefer X because it is flexible.")
    for v in (ev.delivery, ev.language_use, ev.topic_development, ev.score):
        assert 0 <= v <= 4
    assert 0 <= ev.scaled_30 <= 30


async def test_handle_response_persists_attempt(tmp_path):
    from tutor.bot.speaking import handle_response

    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id
        svc.repo.ensure_subscriber(user)
        task = SpeakingTaskPayload(task_type="independent", prompt="Describe your hometown.")
        state = FakeState({"task": task.model_dump(), "phase": "respond"})

        await handle_response(
            svc, None, user, state, "My hometown is a vibrant coastal city with great food."
        )

        stats = svc.repo.speaking_scores(user)
        assert stats["count"] == 1
        assert stats["last"] is not None
        # FSM state was cleared after scoring.
        assert await state.get_data() == {}


async def test_handle_response_too_short_does_not_persist(tmp_path):
    from tutor.bot.speaking import handle_response

    settings = _settings(tmp_path)
    with open_services(settings) as svc:
        user = settings.admin_user_id
        svc.repo.ensure_subscriber(user)
        task = SpeakingTaskPayload(task_type="independent", prompt="Q?")
        state = FakeState({"task": task.model_dump()})

        await handle_response(svc, None, user, state, "ok")  # < 5 chars
        assert svc.repo.speaking_scores(user)["count"] == 0
