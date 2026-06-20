"""RSS cadence calendar, entry normalization, and lazy transcription."""

from __future__ import annotations

from tutor.app import open_services
from tutor.config import Settings
from tutor.domain.enums import Cadence, ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.calendar import CATALOG, Podcast, due_today
from tutor.ingest.rss import _duration_sec, normalize_entry
from tutor.pipeline import build_evaluation

_POD = Podcast("Short Wave", "https://feeds.npr.org/510351/podcast.xml", Cadence.DAILY)


def test_due_today_cadence():
    daily = {p.name for p in CATALOG if p.cadence == Cadence.DAILY}
    # Tuesday -> daily only
    assert {p.name for p in due_today(1)} == daily
    # Monday -> daily + thrice
    mon = {p.name for p in due_today(0)}
    assert daily <= mon and "Planet Money" in mon and "Acquired" not in mon
    # Saturday -> daily + weekend
    sat = {p.name for p in due_today(5)}
    assert daily <= sat and "Acquired" in sat and "Planet Money" not in sat


def test_duration_parsing():
    assert _duration_sec({"itunes_duration": "25:30"}) == 1530
    assert _duration_sec({"itunes_duration": "1:02:03"}) == 3723
    assert _duration_sec({"itunes_duration": "1500"}) == 1500
    assert _duration_sec({}) is None


def test_normalize_entry_podcast():
    entry = {
        "title": "Why mitochondria matter",
        "enclosures": [{"href": "https://cdn/ep.mp3"}],
        "id": "guid-1",
        "link": "https://show/ep",
        "itunes_duration": "25:30",
        "published_parsed": (2026, 6, 21, 8, 0, 0, 0, 0, 0),
    }
    raw = normalize_entry(entry, _POD)
    assert raw is not None
    assert raw.content_type == ContentType.PODCAST
    assert raw.source_type == SourceType.RSS
    assert raw.audio_url == "https://cdn/ep.mp3"
    assert raw.body_text == ""  # lazy
    assert raw.duration_sec == 1530
    assert raw.cadence_bucket == Cadence.DAILY


def test_normalize_entry_skips_without_audio():
    assert normalize_entry({"title": "No audio"}, _POD) is None


async def test_build_evaluation_transcribes_podcast_lazily(tmp_path):
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "t.db"),
        data_dir=str(tmp_path / "data"),
        soul_dir=str(tmp_path / "soul"),
        llm_backend="stub",
        stt_backend="stub",
        notifier_backend="stub",
        anki_backend="genanki",
    )
    with open_services(settings) as svc:
        user = settings.admin_user_id
        audio = tmp_path / "ep.mp3"
        audio.write_bytes(b"fake-audio")  # local file -> no download needed
        cid = svc.repo.add_content(
            RawItem(
                source_type=SourceType.RSS,
                source_ref="Short Wave",
                external_id="e1",
                content_type=ContentType.PODCAST,
                title="Episode",
                audio_url=str(audio),
                body_text="",
            ),
            user,
        )

        quiz = await build_evaluation(svc, cid, user)
        body = svc.repo.get(cid).body_text
        assert "stub transcript" in body  # filled lazily by the stub STT
        assert len(quiz.questions) == 3
