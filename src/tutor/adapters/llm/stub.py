"""Deterministic offline LLM. No network; reproducible output for tests."""

from __future__ import annotations

import types
import typing

from pydantic import BaseModel

from tutor.eval.schemas import QuestionPayload, ReadingQuizPayload


class StubLLMClient:
    async def complete(self, system: str, user: str) -> str:
        return f"[stub-llm reply] {user.strip()[:120]}"

    async def complete_json[T: BaseModel](self, system: str, user: str, schema: type[T]) -> T:
        if schema is ReadingQuizPayload:
            return typing.cast(T, _stub_reading_quiz())
        return _build_generic(schema)


def _stub_reading_quiz() -> ReadingQuizPayload:
    return ReadingQuizPayload(
        questions=[
            QuestionPayload(
                prompt=f"Stub reading question {i + 1}: what is the main idea?",
                options=["First option", "Second option", "Third option", "Fourth option"],
                correct_index=i % 4,
                explanation="Deterministic stub explanation.",
            )
            for i in range(3)
        ]
    )


def _build_generic[T: BaseModel](schema: type[T]) -> T:
    """Best-effort deterministic instance for unknown schemas."""
    try:
        return schema()  # all-defaults path
    except Exception:
        values = {name: _stub_for(name, f.annotation) for name, f in schema.model_fields.items()}
        return schema(**values)


def _stub_for(name: str, annotation: object) -> object:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        annotation = next(a for a in typing.get_args(annotation) if a is not type(None))
        origin = typing.get_origin(annotation)
    if origin in (list, typing.List):  # noqa: UP006
        inner = (typing.get_args(annotation) or (str,))[0]
        count = 4 if name == "options" else 1
        return [_stub_for(name, inner) for _ in range(count)]
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _build_generic(annotation)
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False
    return f"stub-{name}"
