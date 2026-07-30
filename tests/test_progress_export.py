from __future__ import annotations

import csv
import io
import json
from datetime import date

from conftest import TEST_USER

from tutor.practice.models import Section
from tutor.progress.exporter import export_progress, progress_markdown
from tutor.progress.tracker import IssueInput, ProgressTracker


def _seed(repo) -> None:
    tracker = ProgressTracker(repo)
    tracker.record_issue(
        TEST_USER,
        IssueInput(
            section=Section.WRITING,
            category="grammar",
            skill_code="articles",
            canonical_key="grammar:articles",
            original_excerpt="I went to university",
            correction="I went to the university",
            explanation="Use the article for a specific place.",
        ),
        local_date=date(2026, 7, 30),
    )


def test_markdown_profile_is_dynamic(repo) -> None:
    _seed(repo)
    text = progress_markdown(repo, TEST_USER, today=date(2026, 7, 30))

    assert "TOEFL Progress Profile" in text
    assert "7 days" in text and "30 days" in text and "60 days" in text
    assert "grammar:articles" in text
    assert "Next practice focus" in text
    assert "articles" in text


def test_export_supports_markdown_csv_and_portable_json(repo, tmp_path) -> None:
    _seed(repo)

    md = export_progress(repo, TEST_USER, "md", tmp_path)
    csv_path = export_progress(repo, TEST_USER, "csv", tmp_path)
    json_path = export_progress(repo, TEST_USER, "json", tmp_path)

    assert md.name == "toefl-progress.md"
    rows = list(csv.DictReader(io.StringIO(csv_path.read_text())))
    assert any(row["record_type"] == "issue" for row in rows)
    archive = json.loads(json_path.read_text())
    assert archive["schema_version"] == 1
    assert archive["issues"][0]["canonical_key"] == "grammar:articles"
