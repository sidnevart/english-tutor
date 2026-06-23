"""TOEFL writing: integrated read+listen prompts and rubric (0-5) evaluation."""

from __future__ import annotations

from tutor.eval.essay import evaluate_essay, generate_essay_prompt, next_essay_type
from tutor.eval.schemas import EssayEvalPayload, EssayPromptPayload


class CapturingLLM:
    """Returns a canned payload and records the (system, user) of the last call."""

    def __init__(self, payload) -> None:  # noqa: ANN001
        self._payload = payload
        self.last_system = ""
        self.last_user = ""

    async def complete(self, system, user):  # noqa: ANN001
        return ""

    async def complete_json(self, system, user, schema):  # noqa: ANN001
        self.last_system = system
        self.last_user = user
        return self._payload


def test_essay_type_rotation():
    assert next_essay_type(None) == "independent"
    assert next_essay_type("independent") == "integrated"
    assert next_essay_type("email") == "independent"


async def test_integrated_prompt_carries_passage_and_lecture():
    payload = EssayPromptPayload(
        prompt="Summarize how the lecture responds to the reading.",
        type="integrated",
        passage="Reading with three points.",
        lecture="Lecture that challenges each point.",
    )
    result = await generate_essay_prompt(CapturingLLM(payload), "integrated")
    assert result["passage"] == "Reading with three points."
    assert result["lecture"] == "Lecture that challenges each point."


async def test_evaluate_integrated_includes_sources_and_uses_rubric():
    payload = EssayEvalPayload(score=4, scaled_30=25, strengths=["clear"], weaknesses=[])
    llm = CapturingLLM(payload)
    ev = await evaluate_essay(
        llm,
        "Summarize the lecture in relation to the reading.",
        "The lecture casts doubt on all three reading points...",
        "integrated",
        passage="READING TEXT",
        lecture="LECTURE TEXT",
    )
    assert ev.score == 4
    assert ev.scaled_30 == 25
    # The evaluation prompt must include both sources for an accurate grade.
    assert "READING TEXT" in llm.last_user
    assert "LECTURE TEXT" in llm.last_user
    # Integrated rubric is selected (mentions the lecture/reading relationship).
    assert "Integrated" in llm.last_system


async def test_evaluate_independent_allows_zero_score():
    payload = EssayEvalPayload(score=0, scaled_30=0)
    ev = await evaluate_essay(
        CapturingLLM(payload), "Agree or disagree?", "off topic", "independent"
    )
    assert ev.score == 0  # 0-5 rubric now permits 0