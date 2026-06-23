"""RSS cadence calendar, entry normalization, and lazy transcription."""

from __future__ import annotations

from tutor.app import open_services
from tutor.config import Settings
from tutor.domain.enums import Cadence, ContentType, SourceType
from tutor.domain.models import RawItem
from tutor.ingest.calendar import CATALOG, Podcast, due_today
from tutor.ingest.rss import _duration_sec, _split_segments, normalize_entry
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


def _raw_pod(duration_sec: int | None = None) -> RawItem:
    return RawItem(
        source_type=SourceType.RSS,
        source_ref="Acquired",
        external_id="ep-abc",
        content_type=ContentType.PODCAST,
        title="Big Episode",
        audio_url="https://cdn/ep.mp3",
        body_text="",
        duration_sec=duration_sec,
    )


def test_split_segments_short_episode():
    """Episodes shorter than max_sec are returned unchanged."""
    raw = _raw_pod(duration_sec=1200)  # 20 min
    segs = _split_segments(raw, max_sec=1500)
    assert segs == [raw]


def test_split_segments_unknown_duration():
    """Episodes without duration are returned unchanged."""
    raw = _raw_pod(duration_sec=None)
    segs = _split_segments(raw, max_sec=1500)
    assert segs == [raw]


def test_split_segments_long_episode():
    """A 4-hour episode splits into correct number of 25-min segments."""
    raw = _raw_pod(duration_sec=14400)  # 4 hours = 240 min → 10 segments of 24 min
    segs = _split_segments(raw, max_sec=1500)  # 25 min
    assert len(segs) == 10  # ceil(14400/1500) = 10

    # Each segment has a unique external_id with the ::seg: marker.
    for i, seg in enumerate(segs):
        assert "::seg:" in seg.external_id
        assert f"[Part {i + 1}/10]" in seg.title

    # Segments cover the full duration without overlap or gaps.
    starts = []
    ends = []
    for seg in segs:
        import re

        m = re.search(r"::seg:\d+:(\d+):(\d+)$", seg.external_id)
        assert m, f"segment marker missing in {seg.external_id}"
        starts.append(int(m.group(1)))
        ends.append(int(m.group(2)))

    assert starts[0] == 0
    assert ends[-1] == 14400
    for j in range(1, len(segs)):
        assert starts[j] == ends[j - 1]  # contiguous


def test_split_segments_total_duration():
    """Sum of segment durations equals the original episode duration."""
    raw = _raw_pod(duration_sec=5400)  # 90 min → 4 segments of ~22.5 min
    segs = _split_segments(raw, max_sec=1500)
    assert sum(s.duration_sec for s in segs) == 5400


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
