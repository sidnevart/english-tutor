"""TOEFL essay writing: prompt generation and evaluation.

Supports three essay types that rotate:
  - Independent: opinion essay ("Do you agree or disagree?")
  - Integrated: read + listen + summarize (simplified: read passage + write summary)
  - Email/letter: TOEFL iBT academic discussion style

Evaluation uses the LLM with a structured rubric matching TOEFL scoring criteria.
"""

from __future__ import annotations

from tutor.eval.schemas import EssayEvalPayload, EssayPromptPayload
from tutor.interfaces.llm import LLMClient

_ESSAY_TYPES = ["independent", "integrated", "email"]

_INDEPENDENT_SYSTEM = (
    "You are a TOEFL writing instructor. Generate an Independent Writing task: "
    "a clear opinion prompt (agree/disagree or preference) on an academic or "
    "societal topic. The prompt should be 1-2 sentences, suitable for a 30-minute "
    'essay of 300+ words. Return JSON: {"prompt": "...", "type": "independent"}.'
)

_INTEGRATED_SYSTEM = (
    "You are a TOEFL writing instructor. Generate an Integrated Writing task: "
    "provide a short academic passage (150-200 words) on a topic, then ask the "
    "learner to summarize the main points and explain how they relate to a "
    'hypothetical lecture. Return JSON: {"prompt": "...", "passage": "...", '
    '"type": "integrated"}.'
)

_EMAIL_SYSTEM = (
    "You are a TOEFL writing instructor. Generate an Academic Discussion task: "
    "present a class discussion thread with 2 student opinions, then ask the "
    "learner to contribute their own opinion (100+ words). Return JSON: "
    '{"prompt": "...", "type": "email"}.'
)

_EVAL_SYSTEM = (
    "You are a TOEFL writing evaluator. Score the essay on a 1-5 scale:\n"
    "5 = excellent (clear thesis, well-developed, varied vocabulary, minimal errors)\n"
    "4 = good (clear thesis, adequate development, some errors)\n"
    "3 = fair (unclear thesis or weak development, noticeable errors)\n"
    "2 = weak (poor organization, limited vocabulary, many errors)\n"
    "1 = very weak (barely addresses the task)\n\n"
    "Provide:\n"
    "- score: 1-5\n"
    "- strengths: list of what was done well\n"
    "- weaknesses: list of areas to improve\n"
    "- corrections: list of {error, correction, type} for specific errors\n"
    "- suggestions: list of concrete tips for improvement\n\n"
    "Return JSON matching the EssayEvalPayload schema."
)


def next_essay_type(last_type: str | None) -> str:
    """Rotate essay types: independent → integrated → email → independent."""
    if last_type is None:
        return _ESSAY_TYPES[0]
    try:
        idx = _ESSAY_TYPES.index(last_type)
        return _ESSAY_TYPES[(idx + 1) % len(_ESSAY_TYPES)]
    except ValueError:
        return _ESSAY_TYPES[0]


async def generate_essay_prompt(llm: LLMClient, essay_type: str) -> dict[str, str]:
    """Generate a TOEFL writing prompt of the given type."""
    match essay_type:
        case "integrated":
            system = _INTEGRATED_SYSTEM
        case "email":
            system = _EMAIL_SYSTEM
        case _:
            system = _INDEPENDENT_SYSTEM

    payload = await llm.complete_json(
        system,
        f"Generate a {essay_type} writing prompt.",
        EssayPromptPayload,
    )
    result = {"prompt": payload.prompt, "type": payload.type}
    if hasattr(payload, "passage") and payload.passage:
        result["passage"] = payload.passage
    return result


async def evaluate_essay(
    llm: LLMClient, prompt: str, essay_text: str, essay_type: str
) -> EssayEvalPayload:
    """Evaluate a TOEFL essay and return structured feedback."""
    user = f"ESSAY TYPE: {essay_type}\n\nPROMPT:\n{prompt}\n\nSTUDENT ESSAY:\n{essay_text}"
    return await llm.complete_json(_EVAL_SYSTEM, user, EssayEvalPayload)
