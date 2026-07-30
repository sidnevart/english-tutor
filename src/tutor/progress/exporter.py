"""Current learning-profile reports and MD/CSV/JSON exports."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from tutor.db.repository import Repository


def _rows(repo: Repository, sql: str, params: tuple[object, ...]) -> list[dict[str, object]]:
    return [dict(row) for row in repo.conn.execute(sql, params).fetchall()]


def progress_snapshot(repo: Repository, user_id: int, *, today: date | None = None) -> dict:
    today = today or datetime.now(UTC).date()
    completion: dict[str, dict[str, int]] = {}
    for days in (7, 30, 60):
        cutoff = (today - timedelta(days=days - 1)).isoformat()
        row = repo.conn.execute(
            """
            SELECT COUNT(*) AS due,
                   SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) AS complete
            FROM daily_plan WHERE user_id=? AND plan_date BETWEEN ? AND ?
            """,
            (user_id, cutoff, today.isoformat()),
        ).fetchone()
        completion[str(days)] = {"due": int(row["due"] or 0), "complete": int(row["complete"] or 0)}

    attempts = _rows(
        repo,
        """
        SELECT a.id, c.section, c.task_type, a.status, a.started_at, a.completed_at,
               a.raw_score, a.max_score, a.evaluation_state
        FROM practice_attempt a JOIN catalog_task c ON c.id=a.task_id
        WHERE a.user_id=? ORDER BY a.id
        """,
        (user_id,),
    )
    issues = _rows(
        repo,
        """
        SELECT id, canonical_key, section, category, skill_code, state, severity,
               evaluator_confidence, original_excerpt, correction, explanation,
               first_seen, last_seen
        FROM learning_issue WHERE user_id=? ORDER BY state, last_seen DESC
        """,
        (user_id,),
    )
    skills = _rows(
        repo,
        """
        SELECT skill_code, section, opportunities, successes, accuracy, trend, updated_at
        FROM skill_stat WHERE user_id=? ORDER BY accuracy, opportunities DESC
        """,
        (user_id,),
    )
    issue_events = _rows(
        repo,
        """
        SELECT e.issue_id, e.attempt_id, e.event_type, e.local_date, e.detail_json, e.created_at
        FROM issue_event e JOIN learning_issue i ON i.id=e.issue_id
        WHERE i.user_id=? ORDER BY e.id
        """,
        (user_id,),
    )
    task_stats = _rows(
        repo,
        """
        SELECT c.task_type, COUNT(*) AS attempts,
               AVG(CASE WHEN a.max_score > 0 THEN a.raw_score / a.max_score END) AS accuracy,
               AVG(a.raw_score) AS average_score
        FROM practice_attempt a JOIN catalog_task c ON c.id=a.task_id
        WHERE a.user_id=? AND a.status='completed'
        GROUP BY c.task_type ORDER BY c.task_type
        """,
        (user_id,),
    )
    issue_states = {
        str(row["state"]): int(row["n"])
        for row in repo.conn.execute(
            "SELECT state, COUNT(*) AS n FROM learning_issue WHERE user_id=? GROUP BY state",
            (user_id,),
        ).fetchall()
    }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "user_id": user_id,
        "completion": completion,
        "attempts": attempts,
        "issues": issues,
        "skills": skills,
        "issue_events": issue_events,
        "task_stats": task_stats,
        "issue_states": issue_states,
    }


def progress_markdown(repo: Repository, user_id: int, *, today: date | None = None) -> str:
    snapshot = progress_snapshot(repo, user_id, today=today)
    lines = [
        "# TOEFL Progress Profile",
        "",
        f"Generated: {snapshot['generated_at']}",
        "",
        "## Daily plan completion",
        "",
    ]
    for days in ("7", "30", "60"):
        stats = snapshot["completion"][days]
        percent = round(100 * stats["complete"] / stats["due"]) if stats["due"] else 0
        lines.append(f"- {days} days: {stats['complete']}/{stats['due']} ({percent}%)")
    lines.extend(["", "## Task results", ""])
    for stat in snapshot["task_stats"]:
        accuracy = float(stat["accuracy"] or 0)
        lines.append(
            f"- {stat['task_type']}: {stat['attempts']} block(s), "
            f"{accuracy:.0%} of available points"
        )
    if snapshot["attempts"]:
        for attempt in snapshot["attempts"]:
            score = (
                "pending"
                if attempt["raw_score"] is None
                else f"{attempt['raw_score']}/{attempt['max_score']}"
            )
            lines.append(f"- {attempt['task_type']}: {score} — {attempt['status']}")
    else:
        lines.append("No completed attempts yet.")
    lines.extend(["", "## Learning issues", ""])
    states = snapshot["issue_states"]
    lines.append(
        "States: "
        + ", ".join(
            f"{state}={states.get(state, 0)}"
            for state in ("new", "recurring", "improving", "resolved", "relapsed")
        )
    )
    lines.append("")
    if snapshot["issues"]:
        for issue in snapshot["issues"]:
            lines.extend(
                [
                    f"### {issue['canonical_key']} — {issue['state']}",
                    f"- Section: {issue['section']}; skill: {issue['skill_code']}",
                    f"- Example: {issue['original_excerpt']}",
                    f"- Correction: {issue['correction']}",
                    f"- Why: {issue['explanation']}",
                    "",
                ]
            )
    else:
        lines.append("No learning issues recorded yet.")
    lines.extend(["", "## Skill accuracy", ""])
    if snapshot["skills"]:
        for skill in snapshot["skills"]:
            trend = float(skill["trend"] or 0)
            lines.append(
                f"- {skill['skill_code']}: {float(skill['accuracy']):.0%} "
                f"({skill['successes']}/{skill['opportunities']}), "
                f"latest change {trend:+.0%}"
            )
    else:
        lines.append("No skill checks recorded yet.")
    active_issues = [issue for issue in snapshot["issues"] if issue["state"] != "resolved"]
    weak_skills = sorted(
        snapshot["skills"], key=lambda row: (float(row["accuracy"]), -int(row["opportunities"]))
    )
    focus = [str(issue["skill_code"]) for issue in active_issues[:3]]
    focus.extend(
        str(skill["skill_code"]) for skill in weak_skills if str(skill["skill_code"]) not in focus
    )
    lines.extend(["", "## Next practice focus", ""])
    lines.extend(f"- {skill}" for skill in focus[:5])
    if not focus:
        lines.append("Complete a block to establish the next focus.")
    return "\n".join(lines).rstrip() + "\n"


def _csv_text(snapshot: dict) -> str:
    output = io.StringIO()
    fields = [
        "record_type",
        "id",
        "section",
        "task_type",
        "canonical_key",
        "state",
        "score",
        "max_score",
        "date",
        "detail",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for attempt in snapshot["attempts"]:
        writer.writerow(
            {
                "record_type": "attempt",
                "id": attempt["id"],
                "section": attempt["section"],
                "task_type": attempt["task_type"],
                "score": attempt["raw_score"],
                "max_score": attempt["max_score"],
                "date": attempt["completed_at"],
                "detail": attempt["evaluation_state"],
            }
        )
    for issue in snapshot["issues"]:
        writer.writerow(
            {
                "record_type": "issue",
                "id": issue["id"],
                "section": issue["section"],
                "canonical_key": issue["canonical_key"],
                "state": issue["state"],
                "date": issue["last_seen"],
                "detail": f"{issue['original_excerpt']} -> {issue['correction']}",
            }
        )
    for event in snapshot["issue_events"]:
        writer.writerow(
            {
                "record_type": "issue_event",
                "id": event["issue_id"],
                "state": event["event_type"],
                "date": event["local_date"],
                "detail": event["detail_json"],
            }
        )
    return output.getvalue()


def export_progress(repo: Repository, user_id: int, fmt: str, output_dir: Path) -> Path:
    fmt = fmt.lower().strip()
    if fmt == "markdown":
        fmt = "md"
    if fmt not in {"md", "csv", "json"}:
        raise ValueError("Export format must be md, csv, or json")
    user_output_dir = output_dir / str(user_id)
    user_output_dir.mkdir(parents=True, exist_ok=True)
    path = user_output_dir / f"toefl-progress.{fmt}"
    snapshot = progress_snapshot(repo, user_id)
    if fmt == "md":
        content = progress_markdown(repo, user_id)
    elif fmt == "csv":
        content = _csv_text(snapshot)
    else:
        content = json.dumps(snapshot, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")
    return path
