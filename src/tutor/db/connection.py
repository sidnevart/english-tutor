"""SQLite connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with row access by name and foreign keys enforced.

    `db_path` may be ``":memory:"`` for tests. Parent directories are created
    for file-backed databases.
    """
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Apply the schema (idempotent), then run lightweight column migrations."""
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the original schema to pre-existing DBs.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, so we check ``PRAGMA table_info``
    first. Each migration is idempotent.
    """
    additions: list[tuple[str, str, str]] = [
        # table, column, column definition
        ("quiz_question", "correct_indices_json", "TEXT NOT NULL DEFAULT ''"),
    ]
    for table, column, definition in additions:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
