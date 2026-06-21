"""Build rich context about the learner for LLM prompts.

Instead of requiring MCP tool-use (which the simple `complete()` interface
doesn't support), we pre-compute a structured learner profile in Python and
inject it into the system prompt. This gives the LLM the same information it
would get from querying a DB — but without needing tool calls.

The profile includes:
  - Recent session errors (with corrections)
  - Recurring error patterns
  - Weak/strong vocabulary
  - Quiz history and scores
  - Content delivery status (what's done, what's pending)
  - Topic performance (weak/strong areas)
  - Practice streak
  - Essay history
"""

from __future__ import annotations

from tutor.db.repository import Repository
from tutor.domain.enums import DeliveryStatus, QuizKind
from tutor.memory.recall import Memory


def build_learner_context(repo: Repository, user_id: int, soul_dir: str) -> str:
    """Build a comprehensive learner profile string for LLM prompts.

    This is the "DB access" layer — instead of MCP tools, we compute
    everything upfront and inject it as structured context. The LLM sees
    the same data it would get from querying, but without needing tools.
    """
    parts: list[str] = []

    # ---- Content status ----
    new_count = repo.count_status(user_id, DeliveryStatus.NEW)
    delivered_count = repo.count_status(user_id, DeliveryStatus.DELIVERED)
    reviewed_count = repo.count_status(user_id, DeliveryStatus.REVIEWED)
    cards = repo.anki_card_count(user_id)
    streak = repo.practice_streak(user_id)

    parts.append(
        f"LEARNER STATUS:\n"
        f"- Practice streak: {streak} day(s)\n"
        f"- Content: {new_count} queued, "
        f"{delivered_count} awaiting review, "
        f"{reviewed_count} completed\n"
        f"- Anki cards: {cards} total"
    )

    # ---- Today's delivered content (not yet quizzed) ----
    delivered = repo.fetch_by_status(user_id, DeliveryStatus.DELIVERED, limit=10)
    if delivered:
        items = []
        for it in delivered:
            kind = "🎧 podcast" if it.content_type.value == "podcast" else "📰 article"
            title = it.title or "Untitled"
            items.append(f"  - {kind}: {title}")
        parts.append("CONTENT AWAITING REVIEW:\n" + "\n".join(items))

    # ---- Recently reviewed content ----
    reviewed = repo.fetch_by_status(user_id, DeliveryStatus.REVIEWED, limit=5)
    if reviewed:
        items = []
        for it in reviewed:
            kind = "🎧" if it.content_type.value == "podcast" else "📰"
            title = it.title or "Untitled"
            quiz = repo.get_quiz(it.id, QuizKind.READING)
            score_str = ""
            if quiz:
                attempts = repo.attempts_for_content(it.id, user_id)
                if attempts:
                    correct = sum(1 for a in attempts if a.is_correct)
                    score_str = f" ({correct}/{len(attempts)} correct)"
            items.append(f"  - {kind} {title}{score_str}")
        parts.append("RECENTLY REVIEWED:\n" + "\n".join(items))

    # ---- Recent session errors ----
    recent_errors = repo.recent_session_errors(user_id, limit=5)
    if recent_errors:
        lines = [
            f"  - {e['error_text']} → {e['correction']} ({e['session_type']})"
            for e in recent_errors
        ]
        parts.append("RECENT ERRORS (from today's sessions):\n" + "\n".join(lines))

    # ---- Recurring errors ----
    top_errors = repo.top_session_errors(user_id, limit=5)
    if top_errors:
        lines = [
            f'  - "{e["error_text"]}" → "{e["correction"]}" ({e["count"]}x)' for e in top_errors
        ]
        parts.append("RECURRING ERRORS:\n" + "\n".join(lines))

    # ---- Weak/strong vocabulary ----
    mem = Memory(soul_dir, user_id)
    weak_words = mem.weak_words(10)
    if weak_words:
        parts.append(f"WEAK VOCABULARY: {', '.join(weak_words)}")

    # ---- Topic performance ----
    weak_topics = repo.weak_topics(user_id, limit=3)
    strong_topics = repo.strong_topics(user_id, limit=3)
    if weak_topics:
        lines = [
            f"  - {t['topic']}: {round(t['avg_score'] * 100)}% ({t['count']} attempts)"
            for t in weak_topics
        ]
        parts.append("WEAKEST TOPICS:\n" + "\n".join(lines))
    if strong_topics:
        lines = [
            f"  - {t['topic']}: {round(t['avg_score'] * 100)}% ({t['count']} attempts)"
            for t in strong_topics
        ]
        parts.append("STRONGEST TOPICS:\n" + "\n".join(lines))

    # ---- Essay history ----
    essay_count = repo.essay_count(user_id)
    if essay_count > 0:
        recent_essays = repo.recent_essays(user_id, limit=3)
        lines = []
        for e in recent_essays:
            score = f"{e['score']}/5" if e["score"] else "unscored"
            lines.append(f"  - {e['essay_type']}: {score}")
        parts.append(f"ESSAYS ({essay_count} total):\n" + "\n".join(lines))

    return "\n\n".join(parts)
