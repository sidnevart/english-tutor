"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from tutor.db import Repository, connect, init_db
from tutor.domain import ContentType, RawItem, SourceType

TEST_USER = 764315256


@pytest.fixture
def repo():
    conn = connect(":memory:")
    init_db(conn)
    r = Repository(conn)
    r.ensure_subscriber(TEST_USER)
    yield r
    conn.close()


@pytest.fixture
def sample_raw():
    def _make(external_id: str = "post-1", body: str = "Hello world.") -> RawItem:
        return RawItem(
            source_type=SourceType.CHANNEL,
            source_ref="1137165265",
            external_id=external_id,
            content_type=ContentType.ARTICLE,
            title="A sample article",
            url="https://t.me/c/1137165265/1",
            body_text=body,
        )

    return _make
