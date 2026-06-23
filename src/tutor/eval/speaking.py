"""TOEFL iBT Speaking: the four official task types, generation, and scoring.

Each task carries the official preparation/response timings. Integrated tasks
(campus, concept, lecture) include a reading and/or a listening transcript that
the bot reads aloud via TTS, mirroring the real exam. Responses are scored on
the official three-trait rubric (Delivery, Language Use, Topic Development),
each 0-4, plus an overall 0-4 and an estimated 0-30 scaled score.
"""

from __future__ import annotations

from tutor.eval.schemas import SpeakingEvalPayload, SpeakingTaskPayload
from tutor.interfaces.llm import LLMClient

TASK_TYPES = ["independent", "campus", "concept", "lecture"]

# (preparation seconds, response seconds) — official TOEFL iBT timings.
TIMINGS: dict[str, tuple[int, int]] = {
    "independent": (15, 45),
    "campus": (30, 60),
    "concept": (30, 60),
    "lecture": (20, 60),
}

TASK_LABELS: dict[str, str] = {
    "independent": "Task 1 · Independent",
    "campus": "Task 2 · Campus situation (read + listen)",
    "concept": "Task 3 · Academic concept (read + listen)",
    "lecture": "Task 4 · Academic lecture (listen)",
}

_GEN_SYSTEM: dict[str, str] = {
    "independent": (
        "You are a TOEFL Speaking item writer. Write ONE Independent Speaking task: "
        "a question asking the test-taker's opinion or preference on a familiar "
        "topic (e.g. 'Some people prefer X, others prefer Y. Which do you prefer and "
        "why?'). Keep reading and listening empty. Return JSON with task_type="
        '"independent", a "prompt", and empty "reading"/"listening".'
    ),
    "campus": (
        "You are a TOEFL Speaking item writer. Write a Task 2 (campus situation):\n"
        "- reading: a short university announcement or letter (80-100 words) proposing "
        "a change or stating a policy.\n"
        "- listening: a conversation transcript where ONE student expresses a clear "
        "opinion (for or against) the announcement and gives TWO reasons. Mark "
        "speakers as 'Man:' / 'Woman:'. Written to be read aloud.\n"
        "- prompt: 'The student expresses an opinion about the announcement. State "
        "the opinion and explain the reasons for holding it.'\n"
        'Return JSON with task_type="campus".'
    ),
    "concept": (
        "You are a TOEFL Speaking item writer. Write a Task 3 (academic concept):\n"
        "- reading: a short academic passage (90-110 words) that defines a concept or "
        "term.\n"
        "- listening: a lecture excerpt where the professor gives ONE or TWO concrete "
        "examples that illustrate the concept. Written to be read aloud.\n"
        "- prompt: 'Using the example(s) from the lecture, explain the concept "
        "introduced in the reading.'\n"
        'Return JSON with task_type="concept".'
    ),
    "lecture": (
        "You are a TOEFL Speaking item writer. Write a Task 4 (academic lecture):\n"
        "- reading: empty.\n"
        "- listening: a lecture excerpt (150-180 words) that explains a topic using "
        "TWO supporting points or examples. Written to be read aloud.\n"
        "- prompt: 'Using points and examples from the lecture, explain [the topic].'\n"
        'Return JSON with task_type="lecture".'
    ),
}

_EVAL_SYSTEM = (
    "You are a certified TOEFL iBT Speaking rater. Score the spoken response "
    "(given as a transcript) using the official three-trait rubric, each 0-4:\n"
    "- delivery: clarity, fluency, pace, pronunciation/intonation (judge from word "
    "choice and coherence since you only have a transcript; note that disfluency "
    "cannot be fully assessed from text).\n"
    "- language_use: grammar range/accuracy and vocabulary.\n"
    "- topic_development: relevance, completeness, coherence, and — for integrated "
    "tasks — accurate use of the reading/listening content.\n\n"
    "Then give an overall score (0-4, the holistic rubric level) and scaled_30 "
    "(map overall: 0->0, 1->8, 2->15, 3->22, 4->30).\n"
    "For integrated tasks, penalize responses that omit or misrepresent the "
    "source content. Provide strengths, improvements, and a short feedback note.\n"
    "Return JSON matching the SpeakingEvalPayload schema."
)


def next_task_type(last_type: str | None) -> str:
    """Rotate through the four task types."""
    if last_type is None or last_type not in TASK_TYPES:
        return TASK_TYPES[0]
    return TASK_TYPES[(TASK_TYPES.index(last_type) + 1) % len(TASK_TYPES)]


async def generate_speaking_task(llm: LLMClient, task_type: str) -> SpeakingTaskPayload:
    """Generate a TOEFL speaking task of the given type."""
    system = _GEN_SYSTEM.get(task_type, _GEN_SYSTEM["independent"])
    payload = await llm.complete_json(
        system, f"Generate a {task_type} speaking task.", SpeakingTaskPayload
    )
    # Normalize the type in case the model echoes a different label.
    if payload.task_type not in TASK_TYPES:
        payload.task_type = task_type
    return payload


async def evaluate_speaking(
    llm: LLMClient, task: SpeakingTaskPayload, transcript: str
) -> SpeakingEvalPayload:
    """Score a transcribed spoken response against its task."""
    parts = [f"TASK TYPE: {task.task_type}", f"\nPROMPT:\n{task.prompt}"]
    if task.reading:
        parts.append(f"\nREADING:\n{task.reading}")
    if task.listening:
        parts.append(f"\nLISTENING TRANSCRIPT:\n{task.listening}")
    parts.append(f"\nSTUDENT RESPONSE (transcript):\n{transcript}")
    return await llm.complete_json(_EVAL_SYSTEM, "\n".join(parts), SpeakingEvalPayload)
