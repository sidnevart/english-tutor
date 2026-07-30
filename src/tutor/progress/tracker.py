"""Canonical issue grouping, mastery transitions, and skill statistics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from tutor.db.repository import Repository
from tutor.practice.models import Section


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class IssueInput:
    section: Section
    category: str
    skill_code: str
    canonical_key: str
    original_excerpt: str
    correction: str
    explanation: str
    severity: int = 1
    confidence: float = 1.0


class ProgressTracker:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def issue(self, user_id: int, canonical_key: str) -> dict[str, Any] | None:
        row = self.repo.conn.execute(
            "SELECT * FROM learning_issue WHERE user_id=? AND canonical_key=?",
            (user_id, canonical_key),
        ).fetchone()
        return dict(row) if row else None

    def record_issue(
        self,
        user_id: int,
        issue: IssueInput,
        *,
        local_date: date,
        attempt_id: int | None = None,
        legacy_id: int | None = None,
        commit: bool = True,
    ) -> int:
        existing = self.issue(user_id, issue.canonical_key)
        when = local_date.isoformat()
        if existing is None:
            cursor = self.repo.conn.execute(
                """
                INSERT INTO learning_issue
                    (user_id, canonical_key, section, category, skill_code, state, severity,
                     evaluator_confidence, original_excerpt, correction, explanation,
                     first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    issue.canonical_key,
                    issue.section.value,
                    issue.category,
                    issue.skill_code,
                    issue.severity,
                    issue.confidence,
                    issue.original_excerpt,
                    issue.correction,
                    issue.explanation,
                    when,
                    when,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a learning-issue id")
            issue_id = int(cursor.lastrowid)
            state = "new"
        else:
            issue_id = int(existing["id"])
            previous = str(existing["state"])
            state = "relapsed" if previous == "resolved" else "recurring"
            self.repo.conn.execute(
                """
                UPDATE learning_issue SET state=?, severity=?, evaluator_confidence=?,
                    original_excerpt=?, correction=?, explanation=?, last_seen=?,
                    success_dates_json='[]' WHERE id=?
                """,
                (
                    state,
                    issue.severity,
                    issue.confidence,
                    issue.original_excerpt,
                    issue.correction,
                    issue.explanation,
                    when,
                    issue_id,
                ),
            )
        self.repo.conn.execute(
            """
            INSERT OR IGNORE INTO issue_event
                (issue_id, attempt_id, event_type, local_date, detail_json,
                 legacy_session_error_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id,
                attempt_id,
                "relapse" if state == "relapsed" else "occurrence",
                when,
                json.dumps({"excerpt": issue.original_excerpt}),
                legacy_id,
                _now(),
            ),
        )
        if commit:
            self.repo.conn.commit()
        return issue_id

    def record_success(
        self,
        user_id: int,
        canonical_key: str,
        local_date: date,
        *,
        attempt_id: int | None = None,
        commit: bool = True,
    ) -> None:
        existing = self.issue(user_id, canonical_key)
        if not existing:
            return
        dates = set(json.loads(str(existing["success_dates_json"])))
        dates.add(local_date.isoformat())
        state = "resolved" if len(dates) >= 3 else "improving"
        self.repo.conn.execute(
            "UPDATE learning_issue SET state=?, success_dates_json=?, last_seen=? WHERE id=?",
            (state, json.dumps(sorted(dates)), local_date.isoformat(), existing["id"]),
        )
        self.repo.conn.execute(
            """
            INSERT INTO issue_event (issue_id, attempt_id, event_type, local_date, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                existing["id"],
                attempt_id,
                "resolution" if state == "resolved" else "success",
                local_date.isoformat(),
                _now(),
            ),
        )
        if commit:
            self.repo.conn.commit()

    def record_skill_result(
        self,
        user_id: int,
        section: Section,
        skill_code: str,
        success: bool,
        *,
        local_date: date,
        commit: bool = True,
    ) -> None:
        old = self.skill_stat(user_id, skill_code)
        old_opportunities = int(old["opportunities"]) if old else 0
        old_successes = int(old["successes"]) if old else 0
        opportunities = old_opportunities + 1
        successes = old_successes + int(success)
        accuracy = successes / opportunities
        old_accuracy = float(old["accuracy"]) if old else 0.0
        self.repo.conn.execute(
            """
            INSERT INTO skill_stat
                (user_id, skill_code, section, opportunities, successes,
                 accuracy, trend, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, skill_code) DO UPDATE SET
                opportunities=excluded.opportunities, successes=excluded.successes,
                accuracy=excluded.accuracy, trend=excluded.trend, updated_at=excluded.updated_at
            """,
            (
                user_id,
                skill_code,
                section.value,
                opportunities,
                successes,
                accuracy,
                accuracy - old_accuracy,
                _now(),
            ),
        )
        key = f"reading:{skill_code}"
        existing = self.issue(user_id, key)
        if not success:
            self.record_issue(
                user_id,
                IssueInput(
                    section=section,
                    category="reading_skill",
                    skill_code=skill_code,
                    canonical_key=key,
                    original_excerpt="Incorrect answer",
                    correction="Review the answer evidence",
                    explanation=f"Practice {skill_code} using evidence from the text.",
                ),
                local_date=local_date,
                commit=False,
            )
        elif existing and opportunities >= 5 and accuracy >= 0.8:
            self.repo.conn.execute(
                "UPDATE learning_issue SET state='resolved', last_seen=? WHERE id=?",
                (local_date.isoformat(), existing["id"]),
            )
            self.repo.conn.execute(
                """
                INSERT INTO issue_event (issue_id, event_type, local_date, created_at)
                VALUES (?, 'resolution', ?, ?)
                """,
                (existing["id"], local_date.isoformat(), _now()),
            )
        if commit:
            self.repo.conn.commit()

    def skill_stat(self, user_id: int, skill_code: str) -> dict[str, Any] | None:
        row = self.repo.conn.execute(
            "SELECT * FROM skill_stat WHERE user_id=? AND skill_code=?",
            (user_id, skill_code),
        ).fetchone()
        return dict(row) if row else None

    def migrate_legacy_errors(self) -> int:
        rows = self.repo.conn.execute(
            """
            SELECT e.* FROM session_error e
            LEFT JOIN issue_event v ON v.legacy_session_error_id = e.id
            WHERE v.id IS NULL ORDER BY e.id
            """
        ).fetchall()
        for row in rows:
            section = Section.SPEAKING if row["session_type"] == "speak" else Section.WRITING
            error = str(row["error_text"])
            category = str(row["error_type"])
            created = datetime.fromisoformat(str(row["created_at"])).date()
            self.record_issue(
                int(row["user_id"]),
                IssueInput(
                    section=section,
                    category=category,
                    skill_code=f"legacy_{category}",
                    canonical_key=f"legacy:{category}:{error.lower().strip()}",
                    original_excerpt=error,
                    correction=str(row["correction"]),
                    explanation=str(row["context"]),
                ),
                local_date=created,
                legacy_id=int(row["id"]),
            )
        return len(rows)

    def issue_counts(self, user_id: int) -> dict[str, int]:
        rows = self.repo.conn.execute(
            "SELECT state, COUNT(*) AS n FROM learning_issue WHERE user_id=? GROUP BY state",
            (user_id,),
        ).fetchall()
        return {str(row["state"]): int(row["n"]) for row in rows}
