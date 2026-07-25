"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from tutor.db import Repository, connect, init_db

TEST_USER = 764315256


@pytest.fixture
def repo():
    conn = connect(":memory:")
    init_db(conn)
    r = Repository(conn)
    r.ensure_subscriber(TEST_USER)
    yield r
    conn.close()
