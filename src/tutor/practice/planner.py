"""Calendar-based, idempotent TOEFL daily-plan creation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from tutor.catalog import BundledCatalog
from tutor.db.repository import Repository
from tutor.practice.models import Section, TaskType

ROTATION = {
    Section.READING: (
        TaskType.COMPLETE_WORDS,
        TaskType.DAILY_LIFE,
        TaskType.ACADEMIC_PASSAGE,
    ),
    Section.SPEAKING: (TaskType.LISTEN_REPEAT, TaskType.INTERVIEW),
    Section.WRITING: (
        TaskType.BUILD_SENTENCE,
        TaskType.EMAIL,
        TaskType.ACADEMIC_DISCUSSION,
    ),
}


@dataclass(frozen=True)
class PlanEntry:
    id: int
    section: Section
    task_id: str
    task_type: TaskType
    status: str
    payload: dict


@dataclass(frozen=True)
class DailyPlan:
    local_date: date
    entries: tuple[PlanEntry, ...]

    def entry(self, section: Section) -> PlanEntry | None:
        return next((entry for entry in self.entries if entry.section is section), None)


class DailyPlanner:
    def __init__(self, repo: Repository, catalog: BundledCatalog) -> None:
        self.repo = repo
        self.catalog = catalog
        errors = catalog.validate()
        if errors:
            raise ValueError("Invalid bundled catalog: " + "; ".join(errors))
        self.repo.seed_catalog(catalog.tasks)

    def ensure_plan(self, user_id: int, local_date: date) -> DailyPlan:
        day = local_date.isoformat()
        existing = self.repo.plan_entries(user_id, day)
        anchor = date.fromisoformat(self.repo.writing_anchor(user_id, day))
        due = [Section.READING, Section.SPEAKING]
        if (local_date - anchor).days % 2 == 0:
            due.append(Section.WRITING)

        existing_sections = {Section(str(row["section"])) for row in existing}
        additions: list[tuple[str, str]] = []
        for section in due:
            if section in existing_sections:
                continue
            rotation = ROTATION[section]
            rotation_index = self.repo.plan_type_count(user_id, section) % len(rotation)
            task_type = rotation[rotation_index]
            seen = self.repo.seen_task_ids(user_id, section.value, task_type.value)
            weak_skills = self.repo.unresolved_skill_codes(user_id)
            eligible = self.repo.eligible_catalog_tasks(section.value, task_type.value)
            task = BundledCatalog(tuple(eligible)).select(
                section, task_type, seen_ids=seen, weak_skills=weak_skills
            )
            additions.append((section.value, task.id))
        self.repo.insert_plan_entries(user_id, day, additions)
        return self._hydrate(local_date, self.repo.plan_entries(user_id, day))

    @staticmethod
    def _hydrate(local_date: date, rows: list[dict[str, Any]]) -> DailyPlan:
        import json

        return DailyPlan(
            local_date,
            tuple(
                PlanEntry(
                    id=int(row["id"]),
                    section=Section(str(row["section"])),
                    task_id=str(row["task_id"]),
                    task_type=TaskType(str(row["task_type"])),
                    status=str(row["status"]),
                    payload=json.loads(str(row["payload_json"])),
                )
                for row in rows
            ),
        )
