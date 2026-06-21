"""Clean podcast transcripts: strip ads / sponsor reads / intro-outro boilerplate.

Runs through `complete_json` (always direct Ollama, validated) and guards against
the model over-trimming: if the cleaned text is suspiciously short, we keep the
raw transcript rather than lose content.
"""

from __future__ import annotations

from tutor.eval.schemas import CleanedTranscript
from tutor.interfaces.llm import LLMClient

_SYSTEM = (
    "You clean podcast transcripts for language learning. Remove advertising, "
    "sponsor reads, cross-promotions of other shows, and intro/outro boilerplate. "
    "Keep the ACTUAL episode content, preserving the speakers' own wording (do not "
    "summarize or paraphrase). Return only the cleaned transcript text."
)

_MIN_CHARS = 200
_MIN_RATIO = 0.25


async def clean_transcript(llm: LLMClient, raw: str) -> str:
    raw = raw.strip()
    if len(raw) < _MIN_CHARS:
        return raw
    try:
        payload = await llm.complete_json(_SYSTEM, f"Transcript:\n{raw}", CleanedTranscript)
        cleaned = (payload.content or "").strip()
    except Exception:  # noqa: BLE001 — never lose content on a cleaning failure
        return raw
    # Guard against the model dropping too much (or returning junk).
    if len(cleaned) < max(_MIN_CHARS, int(len(raw) * _MIN_RATIO)):
        return raw
    return cleaned
