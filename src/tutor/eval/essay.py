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
    "You are a TOEFL writing instructor. Generate a complete Integrated Writing "
    "task (read + listen + write):\n"
    "1. passage: a short academic reading (180-230 words) that presents THREE "
    "   distinct points/arguments on a topic.\n"
    "2. lecture: a spoken lecture transcript (180-230 words) by a professor that "
    "   CASTS DOUBT ON or CHALLENGES each of the three points from the reading, "
    "   point by point, with specific reasons or examples. Written to be read "
    "   aloud (spoken register, e.g. 'Now, you might think... but actually...').\n"
    "3. prompt: the standard task — 'Summarize the points made in the lecture, "
    "   being sure to explain how they respond to the specific points made in the "
    "   reading passage.'\n"
    'Return JSON: {"prompt": "...", "passage": "...", "lecture": "...", '
    '"type": "integrated"}.'
)

_EMAIL_SYSTEM = (
    "You are a TOEFL writing instructor. Generate an Academic Discussion task: "
    "present a class discussion thread with 2 student opinions, then ask the "
    "learner to contribute their own opinion (100+ words). Return JSON: "
    '{"prompt": "...", "type": "email"}.'
)

_RUBRIC_INDEPENDENT = (
    "Use the official TOEFL Independent Writing rubric (0-5):\n"
    "5 = effectively addresses the task; well organized and developed with clear "
    "explanations/examples; unity and coherence; consistent facility with language "
    "(syntactic variety, appropriate word choice), minor errors only.\n"
    "4 = generally well developed; mostly coherent; occasional errors that don't "
    "obscure meaning.\n"
    "3 = addresses the task with somewhat developed explanations; inconsistent "
    "facility with language; errors that may occasionally obscure meaning.\n"
    "2 = limited development; unclear connections; range of errors that obscure "
    "meaning.\n"
    "1 = little detail/coherence; serious and frequent language errors.\n"
    "0 = merely copies the prompt, off-topic, or blank."
)

_RUBRIC_INTEGRATED = (
    "Use the official TOEFL Integrated Writing rubric (0-5). Reward ACCURATE "
    "selection of the lecture's points and how each one responds to the "
    "corresponding reading point:\n"
    "5 = successfully selects the important information from the lecture and "
    "coherently/accurately presents it in relation to the reading; well organized; "
    "minor language errors only.\n"
    "4 = generally good, but with occasional vagueness, inaccuracy, or omission of "
    "one point or connection.\n"
    "3 = conveys some relevant information but with imprecision, incompleteness, or "
    "noticeable language errors that obscure connections.\n"
    "2 = significant omission or inaccuracy of the lecture's points/connections.\n"
    "1 = little meaningful or accurate content from the lecture.\n"
    "0 = merely copies the reading, off-topic, or blank.\n"
    "Penalize essays that only summarize the reading and ignore the lecture."
)


def _eval_system(essay_type: str) -> str:
    rubric = _RUBRIC_INTEGRATED if essay_type == "integrated" else _RUBRIC_INDEPENDENT
    return (
        "You are a TOEFL writing evaluator.\n\n"
        f"{rubric}\n\n"
        "Provide:\n"
        "- score: 0-5 per the rubric above\n"
        "- scaled_30: the score mapped to TOEFL's 0-30 writing scale (1->8, 2->14, "
        "3->20, 4->25, 5->30; interpolate as needed)\n"
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
    if payload.passage:
        result["passage"] = payload.passage
    if payload.lecture:
        result["lecture"] = payload.lecture
    return result


async def evaluate_essay(
    llm: LLMClient,
    prompt: str,
    essay_text: str,
    essay_type: str,
    *,
    passage: str = "",
    lecture: str = "",
) -> EssayEvalPayload:
    """Evaluate a TOEFL essay and return structured feedback.

    For integrated tasks the reading passage and lecture are included so the
    grader can check whether the response accurately relates the two.
    """
    parts = [f"ESSAY TYPE: {essay_type}", f"\nPROMPT:\n{prompt}"]
    if passage:
        parts.append(f"\nREADING PASSAGE:\n{passage}")
    if lecture:
        parts.append(f"\nLECTURE TRANSCRIPT:\n{lecture}")
    parts.append(f"\nSTUDENT ESSAY:\n{essay_text}")
    return await llm.complete_json(_eval_system(essay_type), "\n".join(parts), EssayEvalPayload)
