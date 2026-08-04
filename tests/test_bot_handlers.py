from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from conftest import TEST_USER

from tutor.bot.handlers import _check_email, _deliver
from tutor.eval.email import EmailCheckResult
from tutor.practice.engine import Attempt
from tutor.practice.models import Section, TaskType


class RecordingNotifier:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    async def send(self, user_id: int, text: str, keyboard=None) -> int:
        self.events.append(("text", text))
        return len(self.events)


class RecordingBot:
    def __init__(self, events: list[tuple[str, str]], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def send_voice(self, user_id: int, audio) -> None:
        if self.fail:
            raise RuntimeError("telegram unavailable")
        self.events.append(("voice", str(audio.path)))


class PassthroughCues:
    async def add_terminal_beep(self, source: Path, output: Path) -> Path:
        return source

    async def duration_seconds(self, path: Path) -> float:
        return 3.2


def listen_repeat_attempt(source: Path) -> Attempt:
    return Attempt(
        id=1,
        user_id=TEST_USER,
        plan_id=2,
        task_id="sp-lr-01",
        section=Section.SPEAKING,
        task_type=TaskType.LISTEN_REPEAT,
        payload={"sentences": ["Welcome to the library."], "audio_paths": [str(source)]},
        status="active",
        current_item=0,
        deadline_at=None,
        raw_score=None,
        max_score=None,
        evaluation_state="not_needed",
    )


async def test_listen_repeat_waits_for_audio_before_speaking_cue(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "sentence.ogg"
    source.write_bytes(b"audio")
    cached = tmp_path / "audio_cache/tts-v3/sp-lr-01/0.ogg"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"current-audio")
    events: list[tuple[str, str]] = []
    svc = SimpleNamespace(
        notifier=RecordingNotifier(events),
        audio_cues=PassthroughCues(),
        settings=SimpleNamespace(data_path=tmp_path),
        synthesizer=None,
    )

    async def fake_sleep(seconds: float) -> None:
        events.append(("sleep", f"{seconds:.1f}"))

    monkeypatch.setattr("tutor.bot.handlers.asyncio.sleep", fake_sleep)

    await _deliver(svc, RecordingBot(events), TEST_USER, listen_repeat_attempt(source))

    assert events[-4:] == [
        ("text", "🔇 Слушайте. Пока не говорите."),
        ("voice", str(cached)),
        ("sleep", "3.5"),
        ("text", "🎙 Можно говорить. Повторите фразу один раз."),
    ]


async def test_listen_repeat_regenerates_audio_in_version_three_cache(
    tmp_path: Path, monkeypatch
) -> None:
    synthesized_paths: list[Path] = []
    cue_paths: list[Path] = []

    class RecordingSynthesizer:
        async def synthesize(self, text: str, out_path: Path) -> Path:
            synthesized_paths.append(out_path)
            output = out_path.with_suffix(".ogg")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"new-speech")
            return output

    class RecordingCues:
        async def add_terminal_beep(self, source: Path, output: Path) -> Path:
            cue_paths.append(output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"new-speech-with-beep")
            return output

        async def duration_seconds(self, path: Path) -> float:
            return 1.0

    async def skip_sleep(seconds: float) -> None:
        pass

    events: list[tuple[str, str]] = []
    svc = SimpleNamespace(
        notifier=RecordingNotifier(events),
        audio_cues=RecordingCues(),
        settings=SimpleNamespace(data_path=tmp_path),
        synthesizer=RecordingSynthesizer(),
    )
    monkeypatch.setattr("tutor.bot.handlers.asyncio.sleep", skip_sleep)
    stale_audio = tmp_path / "old-cache.ogg"
    stale_audio.write_bytes(b"stale-speech")

    await _deliver(
        svc,
        RecordingBot(events),
        TEST_USER,
        listen_repeat_attempt(stale_audio),
    )

    assert synthesized_paths == [tmp_path / "audio_cache/tts-v3/sp-lr-01/0.wav"]
    assert cue_paths == [tmp_path / "audio_cache/listen-repeat-cue-v3/sp-lr-01/0.ogg"]


async def test_listen_repeat_omits_speaking_cue_when_voice_delivery_fails(tmp_path: Path) -> None:
    source = tmp_path / "sentence.ogg"
    source.write_bytes(b"audio")
    cached = tmp_path / "audio_cache/tts-v3/sp-lr-01/0.ogg"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"current-audio")
    events: list[tuple[str, str]] = []
    svc = SimpleNamespace(
        notifier=RecordingNotifier(events),
        audio_cues=PassthroughCues(),
        settings=SimpleNamespace(data_path=tmp_path),
        synthesizer=None,
    )

    await _deliver(svc, RecordingBot(events, fail=True), TEST_USER, listen_repeat_attempt(source))

    texts = [value for kind, value in events if kind == "text"]
    assert "🔇 Слушайте. Пока не говорите." in texts
    assert "🎙 Можно говорить. Повторите фразу один раз." not in texts
    assert any("Audio could not be prepared" in text for text in texts)


async def test_check_email_renders_safe_feedback_and_revised_text() -> None:
    class FakeChecker:
        calls: list[tuple[int, str]] = []

        async def check(self, user_id: int, text: str):
            self.calls.append((user_id, text))
            return EmailCheckResult(
                overall_assessment="Clear <script>alert(1)</script>",
                strengths=["Polite tone"],
                revised_email="Dear <Coordinator>,\nPlease help.",
            )

    events: list[tuple[str, str]] = []
    checker = FakeChecker()
    svc = SimpleNamespace(email_checker=checker, notifier=RecordingNotifier(events))

    await _check_email(svc, TEST_USER, "Dear Coordinator, please help.")

    assert checker.calls == [(TEST_USER, "Dear Coordinator, please help.")]
    rendered = "\n".join(text for kind, text in events if kind == "text")
    assert "&lt;script&gt;" in rendered
    assert "Dear &lt;Coordinator&gt;" in rendered
    assert "<script>" not in rendered


async def test_check_email_requires_text_and_skips_evaluation() -> None:
    class UnusedChecker:
        async def check(self, user_id: int, text: str):
            raise AssertionError("checker must not be called")

    events: list[tuple[str, str]] = []
    svc = SimpleNamespace(email_checker=UnusedChecker(), notifier=RecordingNotifier(events))

    await _check_email(svc, TEST_USER, "   ")

    assert "Usage:" in events[0][1]
