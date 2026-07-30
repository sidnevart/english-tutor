from __future__ import annotations

from collections import Counter

from tutor.catalog import BundledCatalog
from tutor.practice.models import Section, TaskType


def test_bundled_catalog_covers_exact_sixty_day_rotation() -> None:
    catalog = BundledCatalog.load()

    counts = Counter(task.task_type for task in catalog.tasks)
    assert counts == {
        TaskType.LISTEN_REPEAT: 30,
        TaskType.INTERVIEW: 30,
        TaskType.COMPLETE_WORDS: 20,
        TaskType.DAILY_LIFE: 20,
        TaskType.ACADEMIC_PASSAGE: 20,
        TaskType.BUILD_SENTENCE: 10,
        TaskType.EMAIL: 10,
        TaskType.ACADEMIC_DISCUSSION: 10,
    }
    assert len({task.id for task in catalog.tasks}) == 150
    assert catalog.validate() == []


def test_catalog_payloads_match_toefl_practice_block_sizes() -> None:
    catalog = BundledCatalog.load()

    for task in catalog.tasks:
        if task.task_type is TaskType.LISTEN_REPEAT:
            assert len(task.payload["sentences"]) == 7
        elif task.task_type is TaskType.INTERVIEW:
            assert len(task.payload["questions"]) == 4
        elif task.task_type is TaskType.COMPLETE_WORDS:
            assert 70 <= len(task.payload["passage"].split()) <= 100
            assert len(task.payload["answers"]) == 10
        elif task.task_type is TaskType.DAILY_LIFE:
            assert 15 <= len(task.payload["passage"].split()) <= 150
            assert 2 <= len(task.payload["questions"]) <= 3
        elif task.task_type is TaskType.ACADEMIC_PASSAGE:
            assert 170 <= len(task.payload["passage"].split()) <= 230
            assert len(task.payload["questions"]) == 5
        elif task.task_type is TaskType.BUILD_SENTENCE:
            assert len(task.payload["items"]) == 10
        else:
            assert task.section is Section.WRITING
            assert task.payload["rubric"]


def test_selector_exhausts_unseen_tasks_before_repeating() -> None:
    catalog = BundledCatalog.load()
    seen: set[str] = set()

    for _ in range(20):
        task = catalog.select(Section.READING, TaskType.COMPLETE_WORDS, seen_ids=seen)
        assert task.id not in seen
        seen.add(task.id)

    repeated = catalog.select(Section.READING, TaskType.COMPLETE_WORDS, seen_ids=seen)
    assert repeated.id in seen
