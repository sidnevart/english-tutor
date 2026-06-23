"""Inline keyboard builders and callback parsing."""

from __future__ import annotations

from tutor.bot.keyboards import evening_actions, parse_callback


def test_evening_actions_with_and_without_content():
    assert evening_actions(5) == [
        [("💬 Discuss today's material", "discuss:5")],
        [("🎙 Speaking practice", "speak:start")],
    ]
    assert evening_actions(None) == [[("🎙 Speaking practice", "speak:start")]]


def test_parse_callback():
    assert parse_callback("discuss:5") == ("discuss", ["5"])
