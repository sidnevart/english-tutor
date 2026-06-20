"""TelegramNotifier converts ports calls into bot API calls (mocked bot)."""

from __future__ import annotations

from aiogram.types import FSInputFile, InlineKeyboardMarkup

from tutor.adapters.notify.telegram import TelegramNotifier, to_markup


class _FakeMsg:
    message_id = 123


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append(("message", chat_id, text, kwargs))
        return _FakeMsg()

    async def send_document(self, chat_id, document, **kwargs):
        self.calls.append(("document", chat_id, document, kwargs))
        return _FakeMsg()


def test_to_markup_shapes_buttons():
    markup = to_markup([[("A", "a"), ("B", "b")], [("C", "c")]])
    assert isinstance(markup, InlineKeyboardMarkup)
    assert markup.inline_keyboard[0][1].text == "B"
    assert markup.inline_keyboard[0][1].callback_data == "b"


async def test_send_text_with_and_without_keyboard():
    bot = _FakeBot()
    notifier = TelegramNotifier(bot)

    mid = await notifier.send(42, "hello")
    assert mid == 123
    assert bot.calls[-1][3]["reply_markup"] is None

    await notifier.send(42, "pick", keyboard=[[("Yes", "y")]])
    assert isinstance(bot.calls[-1][3]["reply_markup"], InlineKeyboardMarkup)


async def test_send_file(tmp_path):
    f = tmp_path / "deck.apkg"
    f.write_bytes(b"PK\x03\x04")
    bot = _FakeBot()
    notifier = TelegramNotifier(bot)

    mid = await notifier.send_file(42, f, caption="cards")
    assert mid == 123
    kind, chat_id, document, kwargs = bot.calls[-1]
    assert kind == "document"
    assert isinstance(document, FSInputFile)
    assert kwargs["caption"] == "cards"
