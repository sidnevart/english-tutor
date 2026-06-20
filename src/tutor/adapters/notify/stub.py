"""Offline notifier — records what would be sent, for tests and dry runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tutor.interfaces.notifier import Keyboard


@dataclass
class SentMessage:
    user_id: int
    text: str
    keyboard: Keyboard | None = None


@dataclass
class SentFile:
    user_id: int
    path: Path
    caption: str = ""


class StubNotifier:
    def __init__(self) -> None:
        self.messages: list[SentMessage] = []
        self.files: list[SentFile] = []
        self._next_id = 0

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def send(self, user_id: int, text: str, keyboard: Keyboard | None = None) -> int:
        self.messages.append(SentMessage(user_id, text, keyboard))
        return self._id()

    async def send_file(self, user_id: int, path: Path, caption: str = "") -> int:
        self.files.append(SentFile(user_id, Path(path), caption))
        return self._id()
