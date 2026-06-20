"""The delivery state machine: legal flow, Python guard, and DB trigger."""

from __future__ import annotations

import sqlite3

import pytest

from tutor.db import InvalidTransition
from tutor.domain import DeliveryStatus


def test_legal_flow_sets_timestamps(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    assert cid is not None
    assert repo.get(cid).status == DeliveryStatus.NEW

    repo.mark_delivered(cid)
    item = repo.get(cid)
    assert item.status == DeliveryStatus.DELIVERED
    assert item.delivered_at is not None

    repo.mark_reviewed(cid)
    item = repo.get(cid)
    assert item.status == DeliveryStatus.REVIEWED
    assert item.reviewed_at is not None


def test_illegal_transition_raises_in_python(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    with pytest.raises(InvalidTransition):
        repo.mark_reviewed(cid)  # NEW -> REVIEWED is illegal


def test_reviewed_is_terminal(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    repo.mark_delivered(cid)
    repo.mark_reviewed(cid)
    with pytest.raises(InvalidTransition):
        repo.mark_delivered(cid)


def test_requeue_from_failed_and_skipped(repo, sample_raw):
    cid = repo.add_content(sample_raw(), user_id=764315256)
    repo.mark_failed(cid)
    repo.requeue(cid)
    assert repo.get(cid).status == DeliveryStatus.NEW

    repo.mark_skipped(cid)
    repo.requeue(cid)
    assert repo.get(cid).status == DeliveryStatus.NEW


def test_dedup_returns_none_on_duplicate(repo, sample_raw):
    first = repo.add_content(sample_raw(external_id="dup"), user_id=764315256)
    second = repo.add_content(sample_raw(external_id="dup"), user_id=764315256)
    assert first is not None
    assert second is None


def test_trigger_blocks_illegal_transition_bypassing_python(repo, sample_raw):
    """Defense-in-depth: a raw UPDATE that skips the Python guard is rejected."""
    cid = repo.add_content(sample_raw(), user_id=764315256)
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute("UPDATE content_item SET status = 'REVIEWED' WHERE id = ?", (cid,))
        repo.conn.commit()
