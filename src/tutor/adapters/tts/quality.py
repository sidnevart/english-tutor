"""Measure generated speech and reject heavily fragmented TTS output."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

_SILENCE_DURATION = re.compile(r"silence_duration: ([0-9.]+)")


@dataclass(frozen=True)
class AudioStats:
    duration_seconds: float
    pause_events: int
    silence_seconds: float

    @property
    def silence_ratio(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.silence_seconds / self.duration_seconds


async def probe_duration(path: Path) -> float:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError("ffprobe failed to measure audio duration")
    try:
        return float(stdout.decode().strip())
    except ValueError as exc:
        raise RuntimeError("ffprobe returned an invalid audio duration") from exc


async def analyze_audio(path: Path) -> AudioStats:
    duration = await probe_duration(path)
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-i",
        str(path),
        "-af",
        "silencedetect=noise=-40dB:d=0.03",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError("ffmpeg failed to analyze TTS audio")
    report = stderr.decode(errors="replace")
    silence_durations = [float(value) for value in _SILENCE_DURATION.findall(report)]
    return AudioStats(
        duration_seconds=duration,
        pause_events=len(silence_durations),
        silence_seconds=sum(silence_durations),
    )


def is_fragmented_speech(stats: AudioStats, *, word_count: int) -> bool:
    pause_limit = max(8, round(word_count * 1.5))
    return stats.pause_events > pause_limit and stats.silence_ratio > 0.5
