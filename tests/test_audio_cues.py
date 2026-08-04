from __future__ import annotations

from pathlib import Path

import pytest

from tutor.adapters.tts.cues import AudioCueComposer


class FakeProcess:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode


async def test_terminal_beep_uses_versioned_cache_and_is_not_appended_twice(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[object, ...]] = []

    async def fake_subprocess(*args, **kwargs):
        calls.append(args)
        Path(str(args[-1])).write_bytes(b"audio-with-one-beep")
        return FakeProcess()

    monkeypatch.setattr("tutor.adapters.tts.cues.asyncio.create_subprocess_exec", fake_subprocess)
    source = tmp_path / "sentence.wav"
    source.write_bytes(b"raw-audio")
    output = tmp_path / "audio_cache" / "listen-repeat-cue-v1" / "task" / "0.ogg"
    composer = AudioCueComposer()

    first = await composer.add_terminal_beep(source, output)
    second = await composer.add_terminal_beep(source, output)

    assert first == output
    assert second == output
    assert output.read_bytes() == b"audio-with-one-beep"
    assert len(calls) == 1
    assert any("sine=frequency=" in str(arg) for arg in calls[0])


async def test_terminal_beep_failure_leaves_no_cache_file(tmp_path: Path, monkeypatch) -> None:
    async def failed_subprocess(*args, **kwargs):
        return FakeProcess(returncode=1)

    monkeypatch.setattr("tutor.adapters.tts.cues.asyncio.create_subprocess_exec", failed_subprocess)
    source = tmp_path / "sentence.wav"
    source.write_bytes(b"raw-audio")
    output = tmp_path / "listen-repeat-cue-v1" / "task" / "0.ogg"

    with pytest.raises(RuntimeError, match="beep"):
        await AudioCueComposer().add_terminal_beep(source, output)

    assert not output.exists()
