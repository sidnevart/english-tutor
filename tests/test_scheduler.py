"""Scheduler jobs (offline) and job registration."""

from __future__ import annotations

from tutor.app import open_services
from tutor.config import Settings
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.pipeline import deliver_new
from tutor.scheduler.jobs import evening_reminder, morning_push, speaking_reminder
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
        # body present so delivery's flashcard step doesn't hit the network here
        body_text=f"Episode {i} transcript about science, ideas, and the natural world.",
    )


async def test_morning_push_delivers_both_types_and_logs(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        for i in range(3):  # 3 articles, 3 podcasts NEW
            svc.repo.add_content(_raw(i), user)
            svc.repo.add_content(_podcast(i), user)

        ids = await morning_push(svc, user)  # defaults: 1 article + 1 podcast
        assert len(ids) == 2
        types = {svc.repo.get(i).content_type for i in ids}
        assert types == {ContentType.ARTICLE, ContentType.PODCAST}

        msgs = svc.notifier.messages  # type: ignore[attr-defined]
        assert any("🎧" in m.text for m in msgs)

        logs = svc.repo.conn.execute("SELECT job FROM schedule_log").fetchall()
        assert any(r["job"] == "morning_push" for r in logs)


async def test_evening_reminder_nudges_anki(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        svc.repo.add_content(_raw(0), user)
        await deliver_new(svc, user, 1)  # -> DELIVERED

        await evening_reminder(svc, user)
        last = svc.notifier.messages[-1]  # type: ignore[attr-defined]
        assert "Anki" in last.text

        logs = svc.repo.conn.execute("SELECT job FROM schedule_log").fetchall()
        assert any(r["job"] == "evening_reminder" for r in logs)


async def test_speaking_reminder_nudges_rotating_type(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        await speaking_reminder(svc, svc.settings.admin_user_id)
        last = svc.notifier.messages[-1]  # type: ignore[attr-defined]
        assert "speaking" in last.text.lower()
        # No prior attempt -> the rotation starts at the first type (independent).
        assert "independent" in last.text.lower()

        logs = svc.repo.conn.execute("SELECT job FROM schedule_log").fetchall()
        assert any(r["job"] == "speaking_reminder" for r in logs)


async def test_article_delivery_rotates_sources(tmp_path):
    from tutor.pipeline import deliver_next_article_rotated

    def art(source_ref: str, eid: str) -> RawItem:
        return RawItem(
            source_type=SourceType.RSS,
            source_ref=source_ref,
            external_id=eid,
            content_type=ContentType.ARTICLE,
            title=f"Article {eid}",
            body_text=f"Distinct {eid} reading passage about science, ideas, and discovery.",
        )

    with open_services(_settings(tmp_path)) as svc:
        user = svc.settings.admin_user_id
        # Pre-deliver a Guardian article so the "last source" is Guardian.
        svc.repo.add_content(art("Guardian/world", "g0"), user)
        await deliver_new(svc, user, 1)
        # Queue one new Guardian + one new Conversation article.
        svc.repo.add_content(art("Guardian/world", "g2"), user)
        svc.repo.add_content(art("The Conversation", "c1"), user)

        chosen = await deliver_next_article_rotated(svc, user)
        assert chosen is not None
        # Rotation avoids the last-delivered source (Guardian) -> picks Conversation.
        assert svc.repo.get(chosen).source_ref == "The Conversation"


async def test_build_scheduler_registers_jobs(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        scheduler = build_scheduler(svc, svc.settings.admin_user_id)
        assert {j.id for j in scheduler.get_jobs()} == {
            "refresh_content",
            "morning_push",
            "daytime_checkin",
            "evening_reminder",
            "essay_reminder",
            "speaking_reminder",
            "weekly_summary",
        }
