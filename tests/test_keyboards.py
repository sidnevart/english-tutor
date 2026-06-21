"""Inline keyboard builders and callback parsing."""

from __future__ import annotations

from tutor.bot.keyboards import answer_options, parse_callback, quiz_invite


def test_quiz_invite():
    assert quiz_invite(7) == [[("📖 Quiz me", "quiz:7")]]


def test_answer_options_are_compact_letter_buttons():
    kb = answer_options(9, 3, ["foo", "bar", "baz", "qux"])
    # one row of single-letter buttons; option text is NOT on the buttons
    assert kb == [
        [
            ("A", "ans:9:3:0"),
            ("B", "ans:9:3:1"),
            ("C", "ans:9:3:2"),
            ("D", "ans:9:3:3"),
        ]
    ]


def test_parse_callback():
    assert parse_callback("ans:9:3:1") == ("ans", ["9", "3", "1"])
    assert parse_callback("quiz:7") == ("quiz", ["7"])
