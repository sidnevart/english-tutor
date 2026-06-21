"""Message rendering."""

from __future__ import annotations

from tutor.domain.models import QuizQuestion
from tutor.render import render_question, render_score


def test_render_question_lists_lettered_options_in_body():
    q = QuizQuestion(
        prompt="What is the main idea?", options=["aa", "bb", "cc", "dd"], correct_index=1
    )
    text = render_question(0, 3, q)
    assert text.startswith("<b>Question 1/3</b>")
    assert "What is the main idea?" in text
    assert "<b>A.</b> aa" in text
    assert "<b>D.</b> dd" in text


def test_render_score_buckets():
    assert "2/3" in render_score(2, 3)
    assert render_score(0, 0).endswith("(0%).")
