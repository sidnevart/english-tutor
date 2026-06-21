"""Guards for the /help body and its sync with the slash menu (COMMANDS).

HELP_TEXT is sent with HTML parse mode, so a malformed tag or a raw "<"/"&"
would make Telegram reject the message at runtime — catch that here instead.
"""

from __future__ import annotations

import re

from tutor.bot.handlers import COMMANDS, HELP_TEXT

# Tags Telegram allows that we actually use in HELP_TEXT.
_ALLOWED_TAGS = {"b", "i", "code"}


def test_every_command_is_documented():
    # /help itself is self-evident (you're reading it); every other command
    # in the slash menu must be described in the rich help body.
    for slug, _ in COMMANDS:
        if slug == "help":
            continue
        assert f"/{slug}" in HELP_TEXT, f"/{slug} missing from HELP_TEXT"


def test_html_tags_are_allowed_and_balanced():
    stack: list[str] = []
    for tag in re.findall(r"<(/?)([a-zA-Z]+)[^>]*>", HELP_TEXT):
        closing, name = tag[0] == "/", tag[1].lower()
        assert name in _ALLOWED_TAGS, f"unexpected tag <{name}>"
        if closing:
            assert stack and stack.pop() == name, f"unbalanced </{name}>"
        else:
            stack.append(name)
    assert not stack, f"unclosed tags: {stack}"


def test_literal_brackets_in_text_are_escaped():
    # The "<question>" placeholder must be escaped so it isn't parsed as a tag.
    assert "<question>" not in HELP_TEXT
    assert "&lt;question&gt;" in HELP_TEXT
    # Every bare "&" must be the start of an HTML entity (&amp; / &lt; / &gt;).
    for m in re.finditer(r"&", HELP_TEXT):
        assert re.match(r"&(amp|lt|gt|quot|#\d+);", HELP_TEXT[m.start() :]), (
            f"unescaped & at offset {m.start()}"
        )
