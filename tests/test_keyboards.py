"""Inline keyboard builders and callback parsing."""

from __future__ import annotations

from tutor.bot.keyboards import evening_actions, parse_callback, quiz_options, quiz_start


def test_evening_actions_with_and_without_content():
    assert evening_actions(5) == [
        [("📖 Quiz me", "quiz:start:5")],
        [("💬 Discuss today's material", "discuss:5")],
        [("🎙 Speaking practice", "speak:start")],
    ]
    assert evening_actions(None) == [[("🎙 Speaking practice", "speak:start")]]


def test_parse_callback():
    assert parse_callback("discuss:5") == ("discuss", ["5"])


def test_quiz_start_keyboard():
    assert quiz_start(7) == [[("📖 Start quiz", "quiz:start:7")]]


def test_quiz_options_single_select():
    # 4 options, single row of letters, no submit button.
    assert quiz_options(4) == [
        [("A", "quiz:opt:0"), ("B", "quiz:opt:1"), ("C", "quiz:opt:2"), ("D", "quiz:opt:3")]
    ]


def test_quiz_options_multi_select_marks_selected_and_adds_submit():
    kb = quiz_options(6, multi=True, selected=[0, 2])
    # 6 letter buttons chunked 4-per-row, selected ones marked, plus a Submit row.
    assert kb[0] == [
        ("✅ A", "quiz:opt:0"),
        ("B", "quiz:opt:1"),
        ("✅ C", "quiz:opt:2"),
        ("D", "quiz:opt:3"),
    ]
    assert kb[1] == [("E", "quiz:opt:4"), ("F", "quiz:opt:5")]
    assert kb[-1] == [("✅ Submit answer", "quiz:submit")]
