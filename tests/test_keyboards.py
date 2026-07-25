"""Inline keyboard builders and callback parsing."""

from __future__ import annotations

from tutor.bot.keyboards import parse_callback, reset_confirm


def test_reset_confirm_has_confirm_and_cancel():
    data = {cb for row in reset_confirm() for _, cb in row}
    assert "reset:confirm" in data
    assert "reset:cancel" in data


def test_parse_callback():
    assert parse_callback("reset:confirm") == ("reset", ["confirm"])
