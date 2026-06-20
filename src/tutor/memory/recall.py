"""Per-user recall: a markdown memory of studied/weak words, fed into prompts.

SQLite remains the source of truth for attempts and vocabulary; this layer is
the human-readable, prompt-shaped memory (the SOUL.md idea) the learner can read
and edit. Files live under ``<soul_dir>/memory/<user_id>/`` (git-ignored).
"""

from __future__ import annotations

import re
from pathlib import Path

from tutor.memory.soul import load_soul

_LINE = re.compile(r"^-\s*(?P<word>[^|]+?)\s*\|\s*(?P<count>\d+)\s*$")


class Memory:
    def __init__(self, soul_dir: str | Path, user_id: int) -> None:
        self.soul_dir = Path(soul_dir)
        self.user_id = int(user_id)
        self.user_dir = self.soul_dir / "memory" / str(self.user_id)

    # ---- persona (system prompt) ----
    def persona(self) -> str:
        soul = load_soul(self.soul_dir)
        profile = self._read("USER.md")
        return f"{soul}\n\n## About this learner\n{profile}" if profile else soul

    # ---- studied / weak words ----
    def add_weak_words(self, words: list[str]) -> None:
        counts = self._weak_counts()
        for raw in words:
            w = raw.strip().lower()
            if w:
                counts[w] = counts.get(w, 0) + 1
        self.user_dir.mkdir(parents=True, exist_ok=True)
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        body = "# Studied / weak words\n\n" + "\n".join(f"- {w} | {c}" for w, c in ordered) + "\n"
        (self.user_dir / "weak_words.md").write_text(body, encoding="utf-8")

    def weak_words(self, limit: int = 20) -> list[str]:
        counts = self._weak_counts()
        return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]

    def recall_hint(self) -> str:
        words = self.weak_words(15)
        if not words:
            return ""
        return (
            "The learner has recently studied these words; where it fits naturally, "
            "reuse or test them to reinforce memory: " + ", ".join(words) + "."
        )

    # ---- helpers ----
    def _read(self, name: str) -> str:
        path = self.user_dir / name
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def _weak_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for line in self._read("weak_words.md").splitlines():
            m = _LINE.match(line.strip())
            if m:
                counts[m["word"].strip().lower()] = int(m["count"])
        return counts
