"""Deterministic audio cues for TOEFL-style speaking turns."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from tutor.adapters.tts.quality import probe_duration


class AudioCueComposer:
    async def duration_seconds(self, path: Path) -> float:
        return await probe_duration(path)

    async def add_terminal_beep(self, source: Path, output: Path) -> Path:
        source = Path(source)
        output = Path(output)
        if output.exists() and output.stat().st_size:
            return output
        if not source.exists():
            raise FileNotFoundError(source)

        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}-{uuid4().hex}.ogg")
        audio_filter = (
            "[0:a]aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=mono[source];"
            "[1:a]adelay=120:all=1,aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=mono[beep];"
            "[source][beep]concat=n=2:v=0:a=1[out]"
        )
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:sample_rate=48000:duration=0.20",
                "-filter_complex",
                audio_filter,
                "-map",
                "[out]",
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                str(temporary),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await process.wait()
            if process.returncode != 0 or not temporary.exists() or not temporary.stat().st_size:
                raise RuntimeError("ffmpeg failed to append the speaking beep")
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
        return output
