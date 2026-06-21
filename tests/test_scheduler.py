"""Scheduler jobs (offline) and job registration."""

from __future__ import annotations

from tutor.app import open_services
from tutor.bot.keyboards import quiz_invite
from tutor.config import Settings
from tutor.domain.enums import ContentType, QuizKind, SourceType
from tutor.domain.models import RawItem
from tutor.pipeline import deliver_new
from tutor.scheduler.jobs import evening_eval, morning_push
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


def _raw(i: int) -> RawItem:
    return RawItem(
        source_type=SourceType.CHANNEL,
        source_ref="1",
        external_id=f"e{i}",
        content_type=ContentType.ARTICLE,
        title=f"Article {i}",
        body_text=f"Distinct passage number {i} about science, discovery, and learning.",
    )


def _podcast(i: int) -> RawItem:
    return RawItem(
        source_type=SourceType.RSS,
        source_ref="Short Wave",
        external_id=f"p{i}",
        content_type=ContentType.PODCAST,
        title=f"Episode {i}",
        audio_url=f"https://cdn/ep{i}.mp3",
        duration_sec=600,
    )


async def test_morning_push_delivers_both_types_and_logs(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        for i in range(3):  # 3 articles, 3 podcasts NEW
            svc.repo.add_content(_raw(i), user)
            svc.repo.add_content(_podcast(i), user)

        ids = await morning_push(svc, user)  # defaults: 2 articles + 2 podcasts
        assert len(ids) == 4

        types = {svc.repo.get(i).content_type for i in ids}
        assert types == {ContentType.ARTICLE, ContentType.PODCAST}

        # a podcast card is rendered with the headphones marker
        msgs = svc.notifier.messages  # type: ignore[attr-defined]
        assert any("🎧" in m.text for m in msgs)

        logs = svc.repo.conn.execute("SELECT job FROM schedule_log").fetchall()
        assert any(r["job"] == "morning_push" for r in logs)


async def test_evening_eval_prepares_quiz_and_nudges(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        cid = svc.repo.add_content(_raw(0), user)
        await deliver_new(svc, user, 1)  # -> DELIVERED

        ids = await evening_eval(svc, user)
        assert ids == [cid]
        assert svc.repo.get_quiz(cid, QuizKind.READING) is not None

        nudge = svc.notifier.messages[-1]  # type: ignore[attr-defined]
        assert nudge.keyboard == quiz_invite(cid)


async def test_build_scheduler_registers_jobs(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        scheduler = build_scheduler(svc, svc.settings.admin_user_id)
        assert {j.id for j in scheduler.get_jobs()} == {
            "refresh_content",
            "morning_push",
            "evening_eval",
        }
