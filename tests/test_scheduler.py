"""Scheduler jobs (offline): push_practice alternation + weekly error summary."""

from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from tutor.app import open_services
from tutor.bot.conversation import ConversationState
from tutor.config import Settings
from tutor.scheduler.jobs import push_practice, weekly_summary
from tutor.scheduler.runner import build_scheduler


def _settings(tmp_path, tz: str = "UTC") -> Settings:
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "t.db"),
        data_dir=str(tmp_path / "data"),
        llm_backend="stub",
        notifier_backend="stub",
        anki_backend="genanki",
        tz=tz,
        soul_dir=str(tmp_path / "soul"),
    )


class _FakeBot:
    id = 123456789


def _state(storage: MemoryStorage, user_id: int) -> FSMContext:
    return FSMContext(
        storage=storage, key=StorageKey(bot_id=_FakeBot.id, chat_id=user_id, user_id=user_id)
    )


async def test_push_practice_starts_and_flips(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        storage = MemoryStorage()

        assert svc.repo.get_pref(uid, "next_practice", "speak") == "speak"
        await push_practice(svc, uid, _FakeBot(), storage)

        assert svc.notifier.messages  # the practice opener was sent
        assert svc.repo.get_pref(uid, "next_practice") == "write"  # flipped
        assert await _state(storage, uid).get_state() == ConversationState.active


async def test_push_practice_alternates_back_to_speak(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        storage = MemoryStorage()
        st = _state(storage, uid)
        await push_practice(svc, uid, _FakeBot(), storage)  # speak -> write
        await st.clear()  # simulate /stop ending the session
        await push_practice(svc, uid, _FakeBot(), storage)  # write -> speak
        assert svc.repo.get_pref(uid, "next_practice") == "speak"


async def test_push_practice_skips_when_session_active(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        storage = MemoryStorage()
        await _state(storage, uid).set_state(ConversationState.active)

        await push_practice(svc, uid, _FakeBot(), storage)

        last = svc.notifier.messages[-1]
        assert "open practice" in last.text
        assert svc.repo.get_pref(uid, "next_practice", "speak") == "speak"  # unchanged


async def test_weekly_summary_reports_errors(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        svc.repo.save_session_errors(
            uid, "speak", [{"type": "grammar", "error": "I goes", "correction": "I go"}]
        )
        await weekly_summary(svc, uid)
        last = svc.notifier.messages[-1]
        assert "Weekly summary" in last.text
        assert "I goes" in last.text


async def test_build_scheduler_registers_jobs(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        scheduler = build_scheduler(svc, svc.settings.admin_user_id)
        assert {j.id for j in scheduler.get_jobs()} == {"push_practice", "weekly_summary"}
