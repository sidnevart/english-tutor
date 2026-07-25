"""The repository: sole writer of the database.

The bot's purpose is capturing speaking/writing errors; `session_error` is the
source of truth for the learner's error diary. Callers use intent verbs
(`save_session_errors`, `error_diary`, `top_session_errors`, ...) rather than
raw SQL.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---- subscribers -------------------------------------------------------
    def ensure_subscriber(self, user_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO subscriber (user_id, joined_at) VALUES (?, ?)",
            (user_id, _now()),
        )
        self.conn.commit()

    # ---- prefs (push alternation, topic index, ...) -----------------------
    def get_pref(self, user_id: int, key: str, default: object = None) -> object:
        """Read a key from the subscriber's prefs_json blob."""
        row = self.conn.execute(
            "SELECT prefs_json FROM subscriber WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return default
        try:
            data = json.loads(row["prefs_json"] or "{}")
        except (ValueError, TypeError):
            return default
        return data.get(key, default)

    def set_pref(self, user_id: int, key: str, value: object) -> None:
        """Write a key into the subscriber's prefs_json blob (upserts the row)."""
        self.ensure_subscriber(user_id)
        row = self.conn.execute(
            "SELECT prefs_json FROM subscriber WHERE user_id = ?", (user_id,)
        ).fetchone()
        try:
            data = json.loads(row["prefs_json"] or "{}") if row else {}
        except (ValueError, TypeError):
            data = {}
        data[key] = value
        self.conn.execute(
            "UPDATE subscriber SET prefs_json = ? WHERE user_id = ?",
            (json.dumps(data), user_id),
        )
        self.conn.commit()

    # ---- logs --------------------------------------------------------------
    def log_job(self, job: str, status: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO schedule_log (job, run_at, status, detail) VALUES (?, ?, ?, ?)",
            (job, _now(), status, detail),
        )
        self.conn.commit()

    def recent_job_logs(self, limit: int = 10) -> list[dict[str, str]]:
        """Return the most recent schedule_log entries."""
        rows = self.conn.execute(
            "SELECT job, run_at, status, detail FROM schedule_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- session errors (the error diary) ---------------------------------
    def save_session_errors(
        self, user_id: int, session_type: str, errors: list[dict[str, str]]
    ) -> None:
        """Persist errors extracted from a speaking/writing session feedback."""
        for e in errors:
            self.conn.execute(
                """
                INSERT INTO session_error
                    (user_id, session_type, error_type, error_text, correction, context, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    session_type,
                    e.get("type", "grammar"),
                    e.get("error", ""),
                    e.get("correction", ""),
                    e.get("context", ""),
                    _now(),
                ),
            )
        self.conn.commit()

    def recent_session_errors(
        self, user_id: int, limit: int = 10, days: int = 1
    ) -> list[dict[str, str]]:
        """Return recent session errors for the user (last N days)."""
        cutoff = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        rows = self.conn.execute(
            """
            SELECT session_type, error_type, error_text, correction, context, created_at
            FROM session_error
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def top_session_errors(self, user_id: int, limit: int = 5) -> list[dict[str, object]]:
        """Return the most frequent recurring errors across all sessions."""
        rows = self.conn.execute(
            """
            SELECT error_type, error_text, correction, COUNT(*) as count
            FROM session_error
            WHERE user_id = ?
            GROUP BY error_type, error_text
            ORDER BY count DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def error_diary(
        self, user_id: int, *, days: int | None = None, limit: int = 200
    ) -> list[dict[str, object]]:
        """One row per distinct (error_type, error_text): how often it recurs,
        when it was first/last seen, and the most recent correction + context.
        Ordered by frequency (then most recent). Powers the /diary export."""
        params: list[object] = [user_id]
        where = "e.user_id = ?"
        if days is not None:
            cutoff = (
                (datetime.now(UTC) - timedelta(days=days))
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .isoformat()
            )
            where += " AND e.created_at >= ?"
            params.append(cutoff)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT e.error_type, e.error_text,
                   (SELECT correction FROM session_error
                    WHERE user_id = e.user_id AND error_type = e.error_type
                          AND error_text = e.error_text
                    ORDER BY created_at DESC LIMIT 1) AS correction,
                   (SELECT context FROM session_error
                    WHERE user_id = e.user_id AND error_type = e.error_type
                          AND error_text = e.error_text
                    ORDER BY created_at DESC LIMIT 1) AS last_context,
                   COUNT(*) AS count,
                   MIN(e.created_at) AS first_seen,
                   MAX(e.created_at) AS last_seen
            FROM session_error e
            WHERE {where}
            GROUP BY e.error_type, e.error_text
            ORDER BY count DESC, last_seen DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def error_count_by_week(self, user_id: int, weeks: int = 4) -> list[dict[str, object]]:
        """Return per-week error count (last N weeks)."""
        cutoff = (
            (datetime.now(UTC) - timedelta(days=weeks * 7))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        rows = self.conn.execute(
            """
            SELECT strftime('%Y-W%W', created_at) AS week,
                   COUNT(*) AS count
            FROM session_error
            WHERE user_id = ? AND created_at >= ?
            GROUP BY week ORDER BY week
            """,
            (user_id, cutoff),
        ).fetchall()
        return [{"week": r["week"], "count": int(r["count"])} for r in rows]

    def practice_streak(self, user_id: int) -> int:
        """Consecutive days with at least one captured error (any practice)."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT DATE(created_at) AS day
            FROM session_error
            WHERE user_id = ?
            ORDER BY day DESC
            """,
            (user_id,),
        ).fetchall()
        if not rows:
            return 0
        streak = 0
        today = datetime.now(UTC).date()
        for row in rows:
            day = datetime.fromisoformat(row["day"]).date()
            expected = today - timedelta(days=streak)
            if day == expected:
                streak += 1
            elif day < expected:
                break
        return streak

    # ---- reset -------------------------------------------------------------
    def reset_progress(self, user_id: int) -> dict[str, int]:
        """Wipe the learner's error diary and prefs. Returns deleted counts."""
        counts: dict[str, int] = {}
        cur = self.conn.execute("DELETE FROM session_error WHERE user_id = ?", (user_id,))
        counts["session_errors"] = cur.rowcount
        self.conn.execute("UPDATE subscriber SET prefs_json = '{}' WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return counts
