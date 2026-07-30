from __future__ import annotations

from conftest import TEST_USER

from tutor.config import Settings
from tutor.db.connection import connect, init_db
from tutor.factory import build_services


def test_legacy_error_database_is_migrated_without_deleting_original_rows() -> None:
    conn = connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE subscriber (
            user_id INTEGER PRIMARY KEY, joined_at TEXT NOT NULL,
            prefs_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE session_error (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            session_type TEXT NOT NULL, error_type TEXT NOT NULL,
            error_text TEXT NOT NULL, correction TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE schedule_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL,
            run_at TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO subscriber (user_id, joined_at) VALUES (?, '2026-01-01T00:00:00+00:00')",
        (TEST_USER,),
    )
    conn.execute(
        """
        INSERT INTO session_error
            (user_id, session_type, error_type, error_text, correction, context, created_at)
        VALUES (?, 'write', 'grammar', 'students is', 'students are', 'old session',
                '2026-01-02T00:00:00+00:00')
        """,
        (TEST_USER,),
    )
    init_db(conn)

    services = build_services(Settings(_env_file=None), conn)

    assert conn.execute("SELECT COUNT(*) FROM session_error").fetchone()[0] == 1
    assert services.tracker.issue(TEST_USER, "legacy:grammar:students is") is not None
    assert services.tracker.migrate_legacy_errors() == 0
    conn.close()


def test_composition_root_builds_catalog_and_router(repo) -> None:
    from tutor.bot.handlers import build_router

    services = build_services(Settings(_env_file=None), repo.conn)

    assert len(services.catalog.tasks) == 150
    assert repo.conn.execute("SELECT COUNT(*) FROM catalog_task").fetchone()[0] == 150
    assert build_router(services) is not None
