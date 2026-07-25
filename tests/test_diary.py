"""Error-diary export: markdown / csv / anki generation."""

from __future__ import annotations

import csv

from tutor.app import open_services
from tutor.config import Settings
from tutor.export.diary import error_card, export_diary, markdown_diary, write_csv_diary


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "t.db"),
        data_dir=str(tmp_path / "data"),
        llm_backend="stub",
        notifier_backend="stub",
        anki_backend="genanki",
        soul_dir=str(tmp_path / "soul"),
    )


def _seed(repo, uid) -> None:
    repo.save_session_errors(
        uid,
        "speak",
        [
            {"type": "grammar", "error": "I goes", "correction": "I go", "context": "I goes home."},
            {"type": "grammar", "error": "I goes", "correction": "I go", "context": "I goes home."},
            {"type": "vocab", "error": "bigly", "correction": "greatly", "context": "..."},
        ],
    )


def test_error_card_builds_front_back():
    card = error_card(
        {
            "error_text": "I goes",
            "correction": "I go",
            "error_type": "grammar",
            "last_context": "ctx",
        }
    )
    assert "I goes" in card.front
    assert card.back == "I go"
    assert "error" in card.tags and "grammar" in card.tags


def test_markdown_groups_by_type_and_counts():
    rows = [
        {
            "error_type": "grammar",
            "error_text": "I goes",
            "correction": "I go",
            "count": 2,
            "first_seen": "a",
            "last_seen": "b",
            "last_context": "ctx",
        },
        {
            "error_type": "vocab",
            "error_text": "bigly",
            "correction": "greatly",
            "count": 1,
            "first_seen": "a",
            "last_seen": "b",
            "last_context": "",
        },
    ]
    md = markdown_diary(rows)
    assert "## grammar" in md
    assert "## vocab" in md
    assert "**Count:** 2" in md


def test_write_csv_columns(tmp_path):
    rows = [
        {
            "error_text": "I goes",
            "correction": "I go",
            "error_type": "grammar",
            "count": 2,
            "first_seen": "a",
            "last_seen": "b",
            "last_context": "ctx",
        }
    ]
    path = tmp_path / "d.csv"
    write_csv_diary(rows, path)
    with path.open(encoding="utf-8") as fh:
        rows_out = list(csv.reader(fh))
    assert rows_out[0] == [
        "error",
        "correction",
        "type",
        "count",
        "first_seen",
        "last_seen",
        "last_context",
    ]
    assert rows_out[1][0] == "I goes"


async def test_export_diary_sends_three_files(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        _seed(svc.repo, uid)
        await export_diary(svc, uid)  # no fmt -> all three
        captions = [f.caption for f in svc.notifier.files]  # type: ignore[attr-defined]
        assert any("Markdown" in c for c in captions)
        assert any("CSV" in c for c in captions)
        assert any("Anki" in c for c in captions)


async def test_export_diary_single_format(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        _seed(svc.repo, uid)
        await export_diary(svc, uid, fmt="csv")
        assert len(svc.notifier.files) == 1  # type: ignore[attr-defined]
        assert "CSV" in svc.notifier.files[0].caption  # type: ignore[attr-defined]


async def test_export_diary_empty_notifies(tmp_path):
    with open_services(_settings(tmp_path)) as svc:
        uid = svc.settings.admin_user_id
        await export_diary(svc, uid)
        assert not svc.notifier.files  # type: ignore[attr-defined]
        assert svc.notifier.messages  # the "empty" notice  # type: ignore[attr-defined]
