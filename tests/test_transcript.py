"""LLM transcript cleaning with over-trim / failure guards."""

from __future__ import annotations

from tutor.eval.schemas import CleanedTranscript
from tutor.eval.transcript import clean_transcript

RAW = "AD: buy our sponsor now. " + ("This is the real episode content about science. " * 30)


class FakeLLM:
    def __init__(self, content: str | None = None, exc: Exception | None = None) -> None:
        self._content = content
        self._exc = exc

    async def complete(self, system: str, user: str) -> str:
        return ""

    async def complete_json(self, system, user, schema):  # noqa: ANN001
        if self._exc:
            raise self._exc
        return CleanedTranscript(content=self._content or "")


async def test_returns_cleaned_when_substantial():
    cleaned = "This is the real episode content about science. " * 30
    out = await clean_transcript(FakeLLM(content=cleaned), RAW)
    assert out == cleaned.strip()
    assert "sponsor" not in out


async def test_falls_back_when_over_trimmed():
    out = await clean_transcript(FakeLLM(content="tiny"), RAW)
    assert out == RAW.strip()


async def test_falls_back_on_error():
    out = await clean_transcript(FakeLLM(exc=RuntimeError("boom")), RAW)
    assert out == RAW.strip()


async def test_short_raw_skips_llm():
    short = "too short to bother cleaning"
    out = await clean_transcript(FakeLLM(content="must not be used"), short)
    assert out == short
