"""The repository: sole writer of the database.

The bot's purpose is capturing speaking/writing errors; `session_error` is the
source of truth for the learner's error diary. Callers use intent verbs
(`save_session_errors`, `error_diary`, `top_session_errors`, ...) rather than
raw SQL.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from tutor.practice.models import CatalogTask


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

    # ---- TOEFL catalog and durable daily plans ----------------------------
    def seed_catalog(self, tasks: Iterable[CatalogTask]) -> int:
        """Insert or refresh validated catalog records without changing stable IDs."""
        count = 0
        for task in tasks:
            self.conn.execute(
                """
                INSERT INTO catalog_task
                    (id, version, section, task_type, topic_domain, cefr, skill_tags_json,
                     payload_json, explanation, provenance, source_url, source_date,
                     validation_state, eligible, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version, payload_json=excluded.payload_json,
                    explanation=excluded.explanation, validation_state=excluded.validation_state,
                    eligible=excluded.eligible
                """,
                (
                    task.id,
                    task.version,
                    task.section.value,
                    task.task_type.value,
                    task.topic_domain,
                    task.cefr,
                    json.dumps(task.skill_tags),
                    json.dumps(task.payload),
                    task.explanation,
                    task.provenance,
                    task.source_url,
                    task.source_date,
                    task.validation_state,
                    _now(),
                ),
            )
            count += 1
        self.conn.commit()
        return count

    def catalog_task(self, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM catalog_task WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def catalog_payloads(self, task_type: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT payload_json FROM catalog_task WHERE task_type=?", (task_type,)
        ).fetchall()
        return [str(row["payload_json"]) for row in rows]

    def eligible_catalog_tasks(self, section: str, task_type: str) -> list[CatalogTask]:
        rows = self.conn.execute(
            """
            SELECT * FROM catalog_task
            WHERE section=? AND task_type=? AND eligible=1 AND validation_state='accepted'
            ORDER BY created_at, id
            """,
            (section, task_type),
        ).fetchall()
        return [
            CatalogTask(
                id=row["id"],
                version=row["version"],
                section=row["section"],
                task_type=row["task_type"],
                topic_domain=row["topic_domain"],
                cefr=row["cefr"],
                skill_tags=json.loads(row["skill_tags_json"]),
                payload=json.loads(row["payload_json"]),
                explanation=row["explanation"],
                provenance=row["provenance"],
                source_url=row["source_url"],
                source_date=row["source_date"],
                validation_state=row["validation_state"],
            )
            for row in rows
        ]

    def unseen_catalog_count(self, user_id: int, task_type: str) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM catalog_task c
            WHERE c.task_type=? AND c.eligible=1 AND c.validation_state='accepted'
              AND NOT EXISTS (
                  SELECT 1 FROM daily_plan p WHERE p.user_id=? AND p.task_id=c.id
              )
            """,
            (task_type, user_id),
        ).fetchone()
        return int(row["n"])

    def log_generation_run(
        self,
        source_url: str,
        task_type: str,
        status: str,
        *,
        validation: list[str] | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        now = _now()
        self.conn.execute(
            """
            INSERT INTO catalog_generation_run
                (source_url, task_type, status, validation_json, diagnostics_json,
                 started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_url,
                task_type,
                status,
                json.dumps(validation or []),
                json.dumps(diagnostics or {}),
                now,
                now,
            ),
        )
        self.conn.commit()

    def latest_generation_run(self) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM catalog_generation_run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def plan_entries(self, user_id: int, plan_date: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT p.id, p.plan_date, p.section, p.task_id, p.status,
                   c.task_type, c.payload_json
            FROM daily_plan p JOIN catalog_task c ON c.id = p.task_id
            WHERE p.user_id = ? AND p.plan_date = ?
            ORDER BY CASE p.section WHEN 'reading' THEN 1 WHEN 'speaking' THEN 2 ELSE 3 END
            """,
            (user_id, plan_date),
        ).fetchall()
        return [dict(row) for row in rows]

    def insert_plan_entry(self, user_id: int, plan_date: str, section: str, task_id: str) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO daily_plan
                (user_id, plan_date, section, task_id, status, created_at)
            VALUES (?, ?, ?, ?, 'not_started', ?)
            """,
            (user_id, plan_date, section, task_id, _now()),
        )
        self.conn.commit()

    def insert_plan_entries(
        self, user_id: int, plan_date: str, entries: list[tuple[str, str]]
    ) -> None:
        with self.conn:
            for section, task_id in entries:
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO daily_plan
                        (user_id, plan_date, section, task_id, status, created_at)
                    VALUES (?, ?, ?, ?, 'not_started', ?)
                    """,
                    (user_id, plan_date, section, task_id, _now()),
                )

    def claim_callback(self, callback_id: str, user_id: int) -> bool:
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO callback_receipt (callback_id, user_id, received_at)
            VALUES (?, ?, ?)
            """,
            (callback_id, user_id, _now()),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def seen_task_ids(self, user_id: int, section: str, task_type: str) -> set[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT p.task_id
            FROM daily_plan p JOIN catalog_task c ON c.id = p.task_id
            WHERE p.user_id = ? AND p.section = ? AND c.task_type = ?
            """,
            (user_id, section, task_type),
        ).fetchall()
        return {str(row["task_id"]) for row in rows}

    def writing_anchor(self, user_id: int, fallback: str) -> str:
        value = self.get_pref(user_id, "writing_anchor")
        if isinstance(value, str):
            return value
        self.set_pref(user_id, "writing_anchor", fallback)
        return fallback

    def plan_notified(self, user_id: int, plan_date: str) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS n FROM daily_plan
            WHERE user_id=? AND plan_date=? AND notified_at IS NOT NULL
            """,
            (user_id, plan_date),
        ).fetchone()
        return int(row["n"]) > 0

    def mark_plan_notified(self, user_id: int, plan_date: str) -> None:
        self.conn.execute(
            "UPDATE daily_plan SET notified_at=? WHERE user_id=? AND plan_date=?",
            (_now(), user_id, plan_date),
        )
        self.conn.commit()

    def plan_type_count(self, user_id: int, section: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM daily_plan WHERE user_id = ? AND section = ?",
            (user_id, section),
        ).fetchone()
        return int(row["n"])

    def unresolved_skill_codes(self, user_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT skill_code FROM learning_issue WHERE user_id=? AND state!='resolved'",
            (user_id,),
        ).fetchall()
        return {str(row["skill_code"]) for row in rows}

    def unresolved_issues(self, user_id: int, section: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT canonical_key, skill_code, correction, explanation FROM learning_issue
            WHERE user_id=? AND section=? AND state!='resolved'
            """,
            (user_id, section),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_attempt_deadline(self, attempt_id: int, deadline_at: str | None) -> None:
        self.conn.execute(
            "UPDATE practice_attempt SET deadline_at=? WHERE id=? AND status='active'",
            (deadline_at, attempt_id),
        )
        self.conn.commit()

    # ---- attempts ---------------------------------------------------------
    def plan_entry(self, plan_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT p.id, p.user_id, p.task_id, p.status AS plan_status,
                   c.section, c.task_type, c.payload_json
            FROM daily_plan p JOIN catalog_task c ON c.id = p.task_id
            WHERE p.id = ?
            """,
            (plan_id,),
        ).fetchone()
        return dict(row) if row else None

    def active_attempt(self, user_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM practice_attempt WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    def resumable_attempt(self, user_id: int, plan_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM practice_attempt
            WHERE user_id = ? AND plan_id = ? AND status IN ('active', 'paused')
            ORDER BY id DESC LIMIT 1
            """,
            (user_id, plan_id),
        ).fetchone()
        return dict(row) if row else None

    def create_attempt(
        self,
        user_id: int,
        plan_id: int,
        task_id: str,
        started_at: str,
        deadline_at: str | None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO practice_attempt
                (user_id, plan_id, task_id, status, started_at, deadline_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (user_id, plan_id, task_id, started_at, deadline_at),
        )
        self.conn.execute("UPDATE daily_plan SET status = 'in_progress' WHERE id = ?", (plan_id,))
        self.conn.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("SQLite did not return an attempt id")
        return int(cursor.lastrowid)

    def resume_attempt(self, attempt_id: int) -> None:
        self.conn.execute(
            "UPDATE practice_attempt SET status = 'active' WHERE id = ?", (attempt_id,)
        )
        self.conn.commit()

    def attempt(self, attempt_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT a.*, c.section, c.task_type, c.payload_json
            FROM practice_attempt a JOIN catalog_task c ON c.id = a.task_id
            WHERE a.id = ?
            """,
            (attempt_id,),
        ).fetchone()
        return dict(row) if row else None

    def save_attempt_item(
        self,
        attempt_id: int,
        item_index: int,
        response_text: str,
        correct: object,
        score: float | None,
        max_score: float,
        feedback: dict[str, object],
        *,
        metrics: dict[str, object] | None = None,
        commit: bool = True,
    ) -> bool:
        cursor = self.conn.execute(
            """
            INSERT OR IGNORE INTO attempt_item
                (attempt_id, item_index, response_text, correct_json, score, max_score,
                 feedback_json, metrics_json, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                item_index,
                response_text,
                json.dumps(correct),
                score,
                max_score,
                json.dumps(feedback),
                json.dumps(metrics or {}),
                _now(),
            ),
        )
        if commit:
            self.conn.commit()
        return cursor.rowcount == 1

    def advance_attempt(
        self,
        attempt_id: int,
        current_item: int,
        *,
        finished: bool,
        evaluation_pending: bool,
        raw_score: float,
        max_score: float,
        deadline_at: str | None = None,
        commit: bool = True,
    ) -> None:
        if finished:
            attempt = self.attempt(attempt_id)
            self.conn.execute(
                """
                UPDATE practice_attempt
                SET status='completed', current_item=?, completed_at=?, raw_score=?, max_score=?,
                    evaluation_state=?, deadline_at=NULL
                WHERE id=?
                """,
                (
                    current_item,
                    _now(),
                    raw_score,
                    max_score,
                    "pending" if evaluation_pending else "complete",
                    attempt_id,
                ),
            )
            if attempt and attempt["plan_id"] is not None:
                self.conn.execute(
                    "UPDATE daily_plan SET status='complete' WHERE id=?", (attempt["plan_id"],)
                )
        else:
            self.conn.execute(
                "UPDATE practice_attempt SET current_item=?, deadline_at=? WHERE id=?",
                (current_item, deadline_at, attempt_id),
            )
        if commit:
            self.conn.commit()

    def attempt_scores(self, attempt_id: int) -> tuple[float, float]:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(score), 0) AS score, COALESCE(SUM(max_score), 0) AS maximum
            FROM attempt_item WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        return float(row["score"]), float(row["maximum"])

    def pause_active_attempt(self, user_id: int) -> int | None:
        row = self.active_attempt(user_id)
        if not row:
            return None
        self.conn.execute("UPDATE practice_attempt SET status='paused' WHERE id=?", (row["id"],))
        self.conn.commit()
        return int(row["id"])

    def attempt_item_count(self, attempt_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM attempt_item WHERE attempt_id=?", (attempt_id,)
        ).fetchone()
        return int(row["n"])

    def attempt_items(self, attempt_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM attempt_item WHERE attempt_id=? ORDER BY item_index", (attempt_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def attempt_draft(self, attempt_id: int) -> list[int]:
        row = self.conn.execute(
            "SELECT feedback_json FROM practice_attempt WHERE id=?", (attempt_id,)
        ).fetchone()
        if not row:
            return []
        try:
            data = json.loads(str(row["feedback_json"]))
            return [int(value) for value in data.get("draft", [])]
        except (TypeError, ValueError):
            return []

    def _set_attempt_draft(self, attempt_id: int, draft: list[int], *, commit: bool = True) -> None:
        self.conn.execute(
            "UPDATE practice_attempt SET feedback_json=? WHERE id=? AND status='active'",
            (json.dumps({"draft": draft}), attempt_id),
        )
        if commit:
            self.conn.commit()

    def append_attempt_draft(self, attempt_id: int, fragment_index: int) -> None:
        draft = self.attempt_draft(attempt_id)
        if fragment_index not in draft:
            draft.append(fragment_index)
            self._set_attempt_draft(attempt_id, draft)

    def undo_attempt_draft(self, attempt_id: int) -> None:
        draft = self.attempt_draft(attempt_id)
        if draft:
            draft.pop()
        self._set_attempt_draft(attempt_id, draft)

    def clear_attempt_draft(self, attempt_id: int, *, commit: bool = True) -> None:
        self._set_attempt_draft(attempt_id, [], commit=commit)

    def render_attempt_draft(self, attempt_id: int) -> str:
        attempt = self.attempt(attempt_id)
        if not attempt:
            return ""
        payload = json.loads(str(attempt["payload_json"]))
        item = payload["items"][int(attempt["current_item"])]
        fragments = item["fragments"]
        return " ".join(str(fragments[index]) for index in self.attempt_draft(attempt_id))

    def complete_attempt_evaluation(
        self,
        attempt_id: int,
        score: float,
        maximum: float,
        feedback: dict[str, object],
        *,
        commit: bool = True,
    ) -> None:
        self.conn.execute(
            """
            UPDATE practice_attempt
            SET raw_score=?, max_score=?, feedback_json=?, evaluation_state='complete'
            WHERE id=?
            """,
            (score, maximum, json.dumps(feedback), attempt_id),
        )
        if commit:
            self.conn.commit()

    def pending_evaluation_ids(self, limit: int = 20) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT id FROM practice_attempt
            WHERE status='completed' AND evaluation_state='pending'
            ORDER BY completed_at LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def overdue_attempt_ids(self, now: str) -> list[int]:
        rows = self.conn.execute(
            """
            SELECT a.id FROM practice_attempt a JOIN catalog_task c ON c.id=a.task_id
            WHERE a.status IN ('active', 'paused')
              AND a.deadline_at IS NOT NULL AND a.deadline_at < ?
              AND c.task_type IN ('email', 'academic_discussion')
            """,
            (now,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

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

    def top_session_errors(self, user_id: int, limit: int = 5) -> list[dict[str, Any]]:
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
    ) -> list[dict[str, Any]]:
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

    def error_count_by_week(self, user_id: int, weeks: int = 4) -> list[dict[str, Any]]:
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
        """Wipe all learner-owned plans, attempts, profile data, and legacy errors."""
        counts: dict[str, int] = {}
        statements = [
            (
                "issue_events",
                "DELETE FROM issue_event WHERE issue_id IN "
                "(SELECT id FROM learning_issue WHERE user_id=?)",
            ),
            (
                "attempt_items",
                "DELETE FROM attempt_item WHERE attempt_id IN "
                "(SELECT id FROM practice_attempt WHERE user_id=?)",
            ),
            ("learning_issues", "DELETE FROM learning_issue WHERE user_id=?"),
            ("skill_stats", "DELETE FROM skill_stat WHERE user_id=?"),
            ("attempts", "DELETE FROM practice_attempt WHERE user_id=?"),
            ("plans", "DELETE FROM daily_plan WHERE user_id=?"),
            ("session_errors", "DELETE FROM session_error WHERE user_id=?"),
        ]
        for key, sql in statements:
            cursor = self.conn.execute(sql, (user_id,))
            counts[key] = cursor.rowcount
        self.conn.execute("UPDATE subscriber SET prefs_json = '{}' WHERE user_id = ?", (user_id,))
        self.conn.commit()
        return counts
