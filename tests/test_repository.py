"""Repository round-trips for the error diary (session_error) + prefs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

TEST_USER = 764315256


def test_save_and_recent_session_errors(repo):
    repo.save_session_errors(
        TEST_USER,
        "speak",
        [
            {"type": "grammar", "error": "I goes", "correction": "I go", "context": "I goes home."},
            {"type": "vocab", "error": "bigly", "correction": "greatly", "context": "..."},
        ],
    )
    recent = repo.recent_session_errors(TEST_USER, limit=10, days=1)
    assert len(recent) == 2
    assert {r["error_text"] for r in recent} == {"I goes", "bigly"}


def test_top_session_errors_groups_by_frequency(repo):
    repo.save_session_errors(
        TEST_USER, "speak", [{"type": "grammar", "error": "I goes", "correction": "I go"}]
    )
    repo.save_session_errors(
        TEST_USER, "write", [{"type": "grammar", "error": "I goes", "correction": "I go"}]
    )
    repo.save_session_errors(
        TEST_USER, "speak", [{"type": "vocab", "error": "bigly", "correction": "greatly"}]
    )
    top = repo.top_session_errors(TEST_USER, limit=5)
    assert top[0]["error_text"] == "I goes"
    assert top[0]["count"] == 2


def test_error_diary_aggregates_first_last_context(repo):
    repo.save_session_errors(
        TEST_USER,
        "speak",
        [{"type": "grammar", "error": "I goes", "correction": "I go", "context": "ctx A"}],
    )
    # Backdate the first occurrence so first_seen < last_seen is observable.
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    repo.conn.execute(
        "UPDATE session_error SET created_at = ? WHERE error_text = ?", (old, "I goes")
    )
    repo.conn.commit()
    repo.save_session_errors(
        TEST_USER,
        "speak",
        [
            {
                "type": "grammar",
                "error": "I goes",
                "correction": "I go (updated)",
                "context": "ctx B",
            }
        ],
    )

    rows = repo.error_diary(TEST_USER)
    assert len(rows) == 1
    r = rows[0]
    assert r["count"] == 2
    assert r["first_seen"] < r["last_seen"]
    assert r["last_context"] == "ctx B"
    assert r["correction"] == "I go (updated)"  # most recent correction wins


def test_error_diary_respects_days_window(repo):
    repo.save_session_errors(
        TEST_USER, "speak", [{"type": "grammar", "error": "old", "correction": "c"}]
    )
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    repo.conn.execute("UPDATE session_error SET created_at = ? WHERE error_text = ?", (old, "old"))
    repo.conn.commit()
    assert repo.error_diary(TEST_USER, days=7) == []
    assert len(repo.error_diary(TEST_USER)) == 1  # no window -> included


def test_error_count_by_week(repo):
    repo.save_session_errors(
        TEST_USER,
        "speak",
        [
            {"type": "grammar", "error": "e1", "correction": "c1"},
            {"type": "vocab", "error": "e2", "correction": "c2"},
        ],
    )
    rows = repo.error_count_by_week(TEST_USER, weeks=2)
    assert sum(r["count"] for r in rows) >= 2


def test_practice_streak_counts_active_days(repo):
    assert repo.practice_streak(TEST_USER) == 0
    repo.save_session_errors(
        TEST_USER, "speak", [{"type": "grammar", "error": "x", "correction": "y"}]
    )
    assert repo.practice_streak(TEST_USER) >= 1


def test_prefs_roundtrip(repo):
    assert repo.get_pref(TEST_USER, "next_practice", "speak") == "speak"
    repo.set_pref(TEST_USER, "next_practice", "write")
    assert repo.get_pref(TEST_USER, "next_practice") == "write"
    repo.set_pref(TEST_USER, "topic_idx", 5)
    assert repo.get_pref(TEST_USER, "topic_idx") == 5
    # independent keys
    assert repo.get_pref(TEST_USER, "next_practice") == "write"


def test_reset_progress_clears_errors_and_prefs(repo):
    repo.save_session_errors(
        TEST_USER, "speak", [{"type": "grammar", "error": "x", "correction": "y"}]
    )
    repo.set_pref(TEST_USER, "topic_idx", 9)
    counts = repo.reset_progress(TEST_USER)
    assert counts["session_errors"] == 1
    assert repo.top_session_errors(TEST_USER) == []
    assert repo.get_pref(TEST_USER, "topic_idx", 0) == 0
