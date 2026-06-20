"""Inline keyboard builders and callback parsing."""

from __future__ import annotations

from tutor.bot.keyboards import answer_options, parse_callback, quiz_invite


def test_quiz_invite():
    assert quiz_invite(7) == [[("📖 Quiz me", "quiz:7")]]


def test_answer_options_letters_and_callbacks():
    kb = answer_options(9, 3, ["foo", "bar"])
    assert kb == [[("A. foo", "ans:9:3:0")], [("B. bar", "ans:9:3:1")]]


def test_parse_callback():
    assert parse_callback("ans:9:3:1") == ("ans", ["9", "3", "1"])
    assert parse_callback("quiz:7") == ("quiz", ["7"])
