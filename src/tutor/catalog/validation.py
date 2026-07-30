"""Exhaustive deterministic validation for every catalog task type."""

from __future__ import annotations

import re

from tutor.practice.models import CatalogTask, TaskType


def validate_task(task: CatalogTask) -> list[str]:
    payload = task.payload
    errors: list[str] = []
    if task.section is not task.task_type.section:
        errors.append("section does not match task type")
    if not task.skill_tags:
        errors.append("at least one skill tag is required")

    kind = task.task_type
    if kind is TaskType.COMPLETE_WORDS:
        words = len(str(payload.get("passage", "")).split())
        answers = payload.get("answers", [])
        valid_answers = (
            isinstance(answers, list)
            and len(answers) == 10
            and all(isinstance(answer, str) and answer.strip() for answer in answers)
        )
        if not 70 <= words <= 100 or not valid_answers:
            errors.append("complete-words requires 70-100 words and ten answers")
        if len(re.findall(r"_+", str(payload.get("passage", "")))) != 10:
            errors.append("complete-words passage requires ten visible gaps")
    elif kind in {TaskType.DAILY_LIFE, TaskType.ACADEMIC_PASSAGE}:
        words = len(str(payload.get("passage", "")).split())
        expected_questions = 5 if kind is TaskType.ACADEMIC_PASSAGE else range(2, 4)
        questions = payload.get("questions", [])
        valid_count = isinstance(questions, list) and (
            len(questions) == expected_questions
            if isinstance(expected_questions, int)
            else len(questions) in expected_questions
        )
        valid_length = (
            170 <= words <= 230 if kind is TaskType.ACADEMIC_PASSAGE else 15 <= words <= 150
        )
        if not valid_count or not valid_length:
            errors.append("reading passage length or question count is invalid")
        errors.extend(_validate_questions(questions))
    elif kind is TaskType.LISTEN_REPEAT:
        sentences = payload.get("sentences", [])
        if (
            not isinstance(sentences, list)
            or len(sentences) != 7
            or not all(isinstance(value, str) and value.strip() for value in sentences)
        ):
            errors.append("listen-repeat requires seven non-empty sentences")
    elif kind is TaskType.INTERVIEW:
        questions = payload.get("questions", [])
        if (
            not isinstance(payload.get("scenario"), str)
            or not str(payload.get("scenario", "")).strip()
            or not isinstance(questions, list)
            or len(questions) != 4
            or not all(isinstance(question, str) and question.strip() for question in questions)
        ):
            errors.append("interview requires a scenario and four questions")
        if payload.get("seconds_per_question") != 45 or not payload.get("rubric"):
            errors.append("interview requires a 45-second window and rubric")
    elif kind is TaskType.BUILD_SENTENCE:
        items = payload.get("items", [])
        if not isinstance(items, list) or len(items) != 10:
            errors.append("build-sentence requires ten items")
        for item in items if isinstance(items, list) else []:
            fragments = item.get("fragments") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or not isinstance(fragments, list)
                or not fragments
                or not all(isinstance(fragment, str) and fragment for fragment in fragments)
                or not isinstance(item.get("answer"), str)
                or not item.get("answer")
                or not isinstance(item.get("skill"), str)
                or not item.get("skill")
            ):
                errors.append("each build-sentence item requires fragments and an answer")
                break
    elif kind is TaskType.EMAIL:
        required: tuple[str, ...] = (
            "scenario",
            "audience",
            "purpose",
            "required_points",
            "rubric",
        )
        if any(not payload.get(key) for key in required) or payload.get("minutes") != 7:
            errors.append(
                "email requires scenario, audience, purpose, points, rubric, and 7 minutes"
            )
    elif kind is TaskType.ACADEMIC_DISCUSSION:
        required = ("professor", "student_a", "student_b", "rubric")
        if any(not payload.get(key) for key in required) or payload.get("minutes") != 10:
            errors.append("discussion requires professor, two students, rubric, and 10 minutes")
    return errors


def _validate_questions(questions: object) -> list[str]:
    if not isinstance(questions, list):
        return ["questions must be a list"]
    errors: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            errors.append("question must be an object")
            continue
        options = question.get("options", [])
        correct = question.get("correct")
        valid_options = (
            isinstance(options, list)
            and len(options) >= 3
            and all(isinstance(option, str) and option.strip() for option in options)
        )
        if not valid_options or len(set(options)) != len(options):
            errors.append("multiple-choice options must be unique")
        if not valid_options or not isinstance(correct, int) or not 0 <= correct < len(options):
            errors.append("multiple-choice answer index is invalid")
        if not all(question.get(key) for key in ("stem", "skill", "evidence", "explanation")):
            errors.append("question requires stem, skill, evidence, and explanation")
    return errors
