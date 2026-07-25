"""Build rich context about the learner for LLM prompts.

Instead of MCP tool-use (which the simple `complete()` interface doesn't
support), we pre-compute a structured learner profile in Python and inject it
into the system prompt: practice streak, recent and recurring errors, and weak
vocabulary. This is what lets the coach personalize without needing tools.
"""

from __future__ import annotations

from tutor.db.repository import Repository
from tutor.memory.recall import Memory


def build_learner_context(repo: Repository, user_id: int, soul_dir: str) -> str:
    """Build a learner profile string for LLM prompts."""
    parts: list[str] = []

    streak = repo.practice_streak(user_id)
    parts.append(f"LEARNER STATUS:\n- Practice streak: {streak} day(s)")

    recent_errors = repo.recent_session_errors(user_id, limit=5)
    if recent_errors:
        lines = [
            f"  - {e['error_text']} → {e['correction']} ({e['session_type']})"
            for e in recent_errors
        ]
        parts.append("RECENT ERRORS (from today's sessions):\n" + "\n".join(lines))

    top_errors = repo.top_session_errors(user_id, limit=5)
    if top_errors:
        lines = [
            f'  - "{e["error_text"]}" → "{e["correction"]}" ({e["count"]}x)' for e in top_errors
        ]
        parts.append("RECURRING ERRORS:\n" + "\n".join(lines))

    weak_words = Memory(soul_dir, user_id).weak_words(10)
    if weak_words:
        parts.append(f"WEAK VOCABULARY: {', '.join(weak_words)}")

    return "\n\n".join(parts)
