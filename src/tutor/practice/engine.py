"""Task-type-aware attempt state machine backed by SQLite."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from tutor.db.repository import Repository
from tutor.practice.models import Section, TaskType

if TYPE_CHECKING:
    from tutor.progress.tracker import ProgressTracker


class ActivePracticeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Attempt:
    id: int
    user_id: int
    plan_id: int
    task_id: str
    section: Section
    task_type: TaskType
    payload: dict
    status: str
    current_item: int
    deadline_at: datetime | None
    raw_score: float | None
    max_score: float | None
    evaluation_state: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_time(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower()))


class PracticeEngine:
    OPEN_TASKS = {TaskType.INTERVIEW, TaskType.EMAIL, TaskType.ACADEMIC_DISCUSSION}

    def __init__(self, repo: Repository, tracker: ProgressTracker | None = None) -> None:
        self.repo = repo
        self.tracker = tracker

    def start(self, user_id: int, plan_id: int, *, now: datetime | None = None) -> Attempt:
        now = now or _utcnow()
        active = self.repo.active_attempt(user_id)
        if active and int(active["plan_id"]) != plan_id:
            raise ActivePracticeError("Finish or cancel the active practice first")
        resumable = self.repo.resumable_attempt(user_id, plan_id)
        if resumable:
            if resumable["status"] == "paused":
                self.repo.resume_attempt(int(resumable["id"]))
            return self._attempt(int(resumable["id"]))
        entry = self.repo.plan_entry(plan_id)
        if not entry or int(entry["user_id"]) != user_id:
            raise LookupError("Daily-plan entry not found")
        if entry["plan_status"] == "complete":
            raise ActivePracticeError("This daily-plan block is already complete")
        task_type = TaskType(str(entry["task_type"]))
        payload = json.loads(str(entry["payload_json"]))
        deadline = self._deadline(task_type, payload, now)
        attempt_id = self.repo.create_attempt(
            user_id, plan_id, str(entry["task_id"]), now.isoformat(), _iso(deadline)
        )
        return self._attempt(attempt_id)

    def submit_current(
        self,
        user_id: int,
        response: str,
        *,
        now: datetime | None = None,
        metrics: dict[str, object] | None = None,
    ) -> Attempt:
        active = self.repo.active_attempt(user_id)
        if not active:
            raise LookupError("No active practice")
        return self.submit(
            user_id,
            int(active["id"]),
            int(active["current_item"]),
            response,
            now=now,
            metrics=metrics,
        )

    def submit(
        self,
        user_id: int,
        attempt_id: int,
        item_index: int,
        response: str,
        *,
        now: datetime | None = None,
        metrics: dict[str, object] | None = None,
    ) -> Attempt:
        now = now or _utcnow()
        attempt = self._attempt(attempt_id)
        if attempt.user_id != user_id:
            raise LookupError("Attempt not found")
        if attempt.status != "active":
            if attempt.status == "completed" and item_index < attempt.current_item:
                return attempt
            raise ActivePracticeError("This attempt is not active")
        if item_index != attempt.current_item:
            return attempt

        if (
            attempt.task_type in {TaskType.EMAIL, TaskType.ACADEMIC_DISCUSSION}
            and attempt.deadline_at is not None
            and now > attempt.deadline_at
        ):
            return self._expire(attempt, now)

        correct, score, maximum, feedback = self._grade(attempt, item_index, response)
        if attempt.task_type is TaskType.INTERVIEW and attempt.deadline_at:
            feedback["late"] = now > attempt.deadline_at
        with self.repo.conn:
            inserted = self.repo.save_attempt_item(
                attempt.id,
                item_index,
                response,
                correct,
                score,
                maximum,
                feedback,
                metrics=metrics,
                commit=False,
            )
            if not inserted:
                return self._attempt(attempt_id)

            if attempt.task_type is TaskType.BUILD_SENTENCE:
                self.repo.clear_attempt_draft(attempt.id, commit=False)

            self._record_progress(
                attempt, response, correct, score, maximum, feedback, now, commit=False
            )

            next_item = item_index + 1
            finished = next_item >= self._item_count(attempt)
            total, total_max = self.repo.attempt_scores(attempt.id)
            self.repo.advance_attempt(
                attempt.id,
                next_item,
                finished=finished,
                evaluation_pending=attempt.task_type in self.OPEN_TASKS,
                raw_score=total,
                max_score=total_max,
                deadline_at=None,
                commit=False,
            )
        return self._attempt(attempt.id)

    def arm_interview_deadline(
        self,
        user_id: int,
        attempt_id: int,
        item_index: int,
        *,
        now: datetime | None = None,
    ) -> Attempt:
        attempt = self._attempt(attempt_id)
        if (
            attempt.user_id != user_id
            or attempt.task_type is not TaskType.INTERVIEW
            or attempt.status != "active"
            or attempt.current_item != item_index
        ):
            raise ActivePracticeError("This interview item is no longer active")
        deadline = (now or _utcnow()) + timedelta(seconds=45)
        self.repo.set_attempt_deadline(attempt.id, _iso(deadline))
        return self._attempt(attempt.id)

    def _record_progress(
        self,
        attempt: Attempt,
        response: str,
        correct: object,
        score: float | None,
        maximum: float,
        feedback: dict,
        now: datetime,
        *,
        commit: bool = True,
    ) -> None:
        if self.tracker is None or score is None:
            return
        success = score >= maximum * 0.8
        if attempt.section is Section.READING:
            skill = str(feedback.get("skill", "vocabulary_in_context"))
            self.tracker.record_skill_result(
                attempt.user_id,
                Section.READING,
                skill,
                success,
                local_date=now.date(),
                commit=commit,
            )
            return
        from tutor.progress.tracker import IssueInput

        if attempt.task_type is TaskType.BUILD_SENTENCE:
            key = "writing:syntax"
            skill = str(feedback.get("skill", "syntax"))
            category = "grammar"
        elif attempt.task_type is TaskType.LISTEN_REPEAT:
            key = "speaking:listen_repeat_alignment"
            skill = "word_order_and_completeness"
            category = "pronunciation"
        else:
            return
        if success:
            self.tracker.record_success(
                attempt.user_id,
                key,
                now.date(),
                attempt_id=attempt.id,
                commit=commit,
            )
        else:
            self.tracker.record_issue(
                attempt.user_id,
                IssueInput(
                    section=attempt.section,
                    category=category,
                    skill_code=skill,
                    canonical_key=key,
                    original_excerpt=response,
                    correction=str(correct),
                    explanation=(
                        "Compare the response with the expected form and practise the pattern."
                    ),
                ),
                local_date=now.date(),
                attempt_id=attempt.id,
                commit=commit,
            )

    def cancel(self, user_id: int) -> int | None:
        return self.repo.pause_active_attempt(user_id)

    def expire_overdue(self, *, now: datetime | None = None) -> list[Attempt]:
        now = now or _utcnow()
        return [
            self._expire(self._attempt(attempt_id), now)
            for attempt_id in self.repo.overdue_attempt_ids(now.isoformat())
        ]

    def _expire(self, attempt: Attempt, now: datetime) -> Attempt:
        with self.repo.conn:
            inserted = self.repo.save_attempt_item(
                attempt.id,
                attempt.current_item,
                "",
                "deadline",
                0.0,
                5.0,
                {"incomplete": True, "reason": "deadline_expired"},
                commit=False,
            )
            if inserted:
                total, total_max = self.repo.attempt_scores(attempt.id)
                self.repo.advance_attempt(
                    attempt.id,
                    attempt.current_item + 1,
                    finished=True,
                    evaluation_pending=False,
                    raw_score=total,
                    max_score=total_max,
                    commit=False,
                )
        return self._attempt(attempt.id)

    def active(self, user_id: int) -> Attempt | None:
        row = self.repo.active_attempt(user_id)
        return self._attempt(int(row["id"])) if row else None

    def get_attempt(self, attempt_id: int) -> Attempt:
        return self._attempt(attempt_id)

    def _attempt(self, attempt_id: int) -> Attempt:
        row = self.repo.attempt(attempt_id)
        if not row:
            raise LookupError("Attempt not found")
        return Attempt(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            plan_id=int(row["plan_id"]),
            task_id=str(row["task_id"]),
            section=Section(str(row["section"])),
            task_type=TaskType(str(row["task_type"])),
            payload=json.loads(str(row["payload_json"])),
            status=str(row["status"]),
            current_item=int(row["current_item"]),
            deadline_at=_parse_time(row["deadline_at"]),
            raw_score=float(row["raw_score"]) if row["raw_score"] is not None else None,
            max_score=float(row["max_score"]) if row["max_score"] is not None else None,
            evaluation_state=str(row["evaluation_state"]),
        )

    @staticmethod
    def _deadline(task_type: TaskType, payload: dict, now: datetime) -> datetime | None:
        if task_type in {TaskType.EMAIL, TaskType.ACADEMIC_DISCUSSION}:
            return now + timedelta(minutes=int(payload["minutes"]))
        return None

    @staticmethod
    def _item_count(attempt: Attempt) -> int:
        payload = attempt.payload
        if attempt.task_type is TaskType.COMPLETE_WORDS:
            return 1
        if attempt.task_type in {
            TaskType.DAILY_LIFE,
            TaskType.ACADEMIC_PASSAGE,
            TaskType.INTERVIEW,
        }:
            return len(payload["questions"])
        if attempt.task_type is TaskType.LISTEN_REPEAT:
            return len(payload["sentences"])
        if attempt.task_type is TaskType.BUILD_SENTENCE:
            return len(payload["items"])
        return 1

    @staticmethod
    def _grade(
        attempt: Attempt, index: int, response: str
    ) -> tuple[object, float | None, float, dict]:
        payload = attempt.payload
        task_type = attempt.task_type
        if task_type is TaskType.COMPLETE_WORDS:
            expected = [_normalize(x) for x in payload["answers"]]
            cleaned = re.sub(r"(?m)^\s*\d+[.)\-:]?\s*", "", response)
            received = [_normalize(x) for x in re.split(r"[,;\n\s]+", cleaned) if _normalize(x)]
            score = float(sum(a == b for a, b in zip(received, expected, strict=False)))
            return expected, score, 10.0, {"received": received, "expected": expected}
        if task_type in {TaskType.DAILY_LIFE, TaskType.ACADEMIC_PASSAGE}:
            question = payload["questions"][index]
            try:
                raw = response.strip()
                selected = int(raw[1:]) if raw.startswith("@") else max(0, int(raw) - 1)
            except ValueError:
                selected = -1
            score = float(selected == int(question["correct"]))
            return (
                question["correct"],
                score,
                1.0,
                {
                    "evidence": question["evidence"],
                    "explanation": question["explanation"],
                    "skill": question["skill"],
                    "selected": selected,
                },
            )
        if task_type is TaskType.BUILD_SENTENCE:
            expected = payload["items"][index]["answer"]
            score = float(_normalize(response) == _normalize(expected))
            return expected, score, 1.0, {"skill": payload["items"][index]["skill"]}
        if task_type is TaskType.LISTEN_REPEAT:
            expected = payload["sentences"][index]
            ratio = SequenceMatcher(
                None, _normalize(response).split(), _normalize(expected).split()
            ).ratio()
            return expected, round(ratio * 5, 2), 5.0, {"alignment": ratio}
        return payload.get("rubric", "structured rubric"), None, 5.0, {"evaluation": "pending"}
