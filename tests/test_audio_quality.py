from __future__ import annotations

from tutor.adapters.tts.quality import AudioStats, is_fragmented_speech


def test_fragmented_speech_requires_many_pauses_and_mostly_silence() -> None:
    broken_third_prompt = AudioStats(
        duration_seconds=3.606,
        pause_events=24,
        silence_seconds=2.270,
    )
    normal_prompt = AudioStats(
        duration_seconds=2.166,
        pause_events=5,
        silence_seconds=0.646,
    )

    assert is_fragmented_speech(broken_third_prompt, word_count=8)
    assert not is_fragmented_speech(normal_prompt, word_count=8)
