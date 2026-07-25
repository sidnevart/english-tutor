"""Ports: the Protocols every feature depends on, never concrete clients."""

from tutor.interfaces.anki import AnkiSink
from tutor.interfaces.llm import LLMClient
from tutor.interfaces.notifier import Keyboard, Notifier
from tutor.interfaces.synthesizer import Synthesizer
from tutor.interfaces.transcriber import Transcriber

__all__ = [
    "AnkiSink",
    "LLMClient",
    "Keyboard",
    "Notifier",
    "Synthesizer",
    "Transcriber",
]
