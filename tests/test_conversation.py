"""Conversation engine sessions (speaking practice), using a fake FSM state."""

from __future__ import annotations

from tutor.app import open_services
from tutor.bot.conversation import end_session, handle_turn, start_speaking
from tutor.config import Settings


class FakeState:
    def __init__(self) -> None:
        self.data: dict = {}
        self.state = None

    async def set_state(self, s) -> None:
        self.state = s

    async def get_state(self):
        return self.state

    async def update_data(self, **kw) -> None:
        self.data.update(kw)

    async def get_data(self) -> dict:
        return dict(self.data)

    async def clear(self) -> None:
        self.data = {}
        self.state = None


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "t.db"),
        data_dir=str(tmp_path / "data"),
        soul_dir=str(tmp_path / "soul"),
        llm_backend="stub",
        notifier_backend="stub",
        tts_backend="stub",
        stt_backend="stub",
    )


async def test_start_speaking_opens_session(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        st = FakeState()
        await start_speaking(svc, None, svc.settings.admin_user_id, st)
        assert st.data["mode"] == "speak"
        assert st.state is not None
        history = st.data["history"]
        assert len(history) == 1 and history[0]["role"] == "coach"
        assert len(svc.notifier.messages) == 1  # type: ignore[attr-defined]


async def test_handle_turn_appends_and_replies(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        st = FakeState()
        await start_speaking(svc, None, user, st)
        before = len(svc.notifier.messages)  # type: ignore[attr-defined]

        await handle_turn(svc, None, user, st, "I really like coffee.")
        roles = [h["role"] for h in st.data["history"]]
        assert roles == ["coach", "learner", "coach"]
        assert len(svc.notifier.messages) == before + 1  # type: ignore[attr-defined]


async def test_end_session_feedback_and_clear(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        st = FakeState()
        await start_speaking(svc, None, user, st)
        await handle_turn(svc, None, user, st, "Hello there.")

        await end_session(svc, user, st)
        assert st.state is None and st.data == {}
        assert "Practice complete" in svc.notifier.messages[-1].text  # type: ignore[attr-defined]
