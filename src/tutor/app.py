"""Composition root: open the database and build wired Services."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from tutor.config import Settings, get_settings
from tutor.db.connection import connect, init_db
from tutor.factory import Services, build_services


@contextmanager
def open_services(settings: Settings | None = None) -> Iterator[Services]:
    """Open a database connection, ensure the schema, and yield Services."""
    settings = settings or get_settings()
    conn = connect(settings.db_file)
    init_db(conn)
    try:
        services = build_services(settings, conn)
        services.repo.ensure_subscriber(settings.admin_user_id)
        yield services
    finally:
        conn.close()
