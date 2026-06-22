"""Quiz quality evaluation — run against real LLM, judge with LLM-as-judge.

Usage:
    python -m pytest tests/eval_quiz_quality.py -v -s

Requires LLM_BACKEND=ollama and a running Ollama server.
Set LLM_BACKEND=stub to run structural-only checks (CI-safe).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tutor.adapters.llm.stub import StubLLMClient
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import ContentItem
from tutor.eval.quiz_builder import build_reading_quiz

# ---------------------------------------------------------------------------
# Real TOEFL-like passages (~700 words each, academic register)
# ---------------------------------------------------------------------------

PASSAGES = [
    {
        "id": "science_climate",
        "title": "The Role of Ocean Currents in Climate Regulation",
        "text": (
            "Ocean currents play a crucial role in regulating Earth's climate by "
            "distributing heat energy from the equator toward the poles. The most "
            "significant of these circulation patterns is the thermohaline circulation, "
            "often referred to as the global conveyor belt. This system is driven by "
            "differences in water density, which are determined by temperature (thermo) "
            "and salinity (haline). In the North Atlantic, cold, salty water sinks to "
            "the deep ocean, drawing warmer surface water northward from the tropics. "
            "This process releases enormous amounts of heat into the atmosphere, "
            "moderating the climate of Western Europe.\n\n"
            "The thermohaline circulation operates on a timescale of centuries, meaning "
            "that changes to the system may not produce immediate effects but can have "
            "profound long-term consequences. Paleoclimate records indicate that abrupt "
            "shutdowns of this circulation have occurred in the past, most notably during "
            "the Younger Dryas period approximately 12,800 years ago. At that time, a "
            "massive influx of freshwater from melting ice sheets disrupted the density-"
            "driven sinking process in the North Atlantic, causing temperatures in Europe "
            "to drop by as much as 10 degrees Celsius within a decade.\n\n"
            "Modern climate scientists have raised concerns that current global warming "
            "could trigger a similar disruption. As Arctic ice melts at an accelerating "
            "rate, the resulting freshwater could dilute the salinity of North Atlantic "
            "surface waters, potentially weakening or shutting down the thermohaline "
            "circulation. Some observational data suggest that this process may already "
            "be underway: measurements taken since the mid-twentieth century indicate a "
            "gradual decline in the density of deep water formation in the Labrador and "
            "Nordic Seas.\n\n"
            "However, the relationship between freshwater input and circulation strength "
            "is more complex than early models suggested. Recent studies incorporating "
            "improved ocean-atmosphere coupling show that the system possesses "
            "considerable resilience. Wind-driven circulation patterns can partially "
            "compensate for weakened thermohaline flow, and the rate of freshwater input "
            "may not yet exceed critical thresholds. Nonetheless, most climate projections "
            "indicate that continued warming will progressively weaken the thermohaline "
            "circulation over the coming century, with potentially significant impacts on "
            "regional weather patterns, marine ecosystems, and sea-level distribution."
        ),
    },
    {
        "id": "history_agriculture",
        "title": "The Neolithic Revolution and Social Complexity",
        "text": (
            "The transition from hunter-gatherer societies to agricultural communities, "
            "known as the Neolithic Revolution, represents one of the most transformative "
            "periods in human history. Beginning approximately 10,000 years ago in the "
            "Fertile Crescent region of the Middle East, this shift fundamentally altered "
            "the relationship between humans and their environment. Rather than depending "
            "on the unpredictable availability of wild resources, communities began to "
            "cultivate selected plant species and domesticate animals, creating a more "
            "reliable, though less varied, food supply.\n\n"
            "The consequences of this transition extended far beyond diet. Permanent "
            "settlements emerged as people invested labor in fields that could not be "
            "abandoned seasonally. This sedentism enabled the accumulation of material "
            "possessions and the development of specialized crafts, since individuals "
            "could devote time to activities other than food procurement. Pottery, "
            "textile production, and metalworking all appear in the archaeological "
            "record following the adoption of agriculture.\n\n"
            "Perhaps most significantly, agricultural surpluses made possible the "
            "emergence of social hierarchies. When a community produces more food than "
            "its members require for immediate survival, some individuals can be freed "
            "from agricultural labor to serve as priests, administrators, soldiers, or "
            "artisans. This division of labor is widely regarded as a prerequisite for "
            "the development of complex political institutions, writing systems, and "
            "monumental architecture — the hallmarks of what anthropologists term "
            '"civilization."\n\n'
            "Critics of this narrative, however, point out that the Neolithic Revolution "
            "was neither sudden nor uniformly beneficial. Archaeological evidence from "
            "multiple sites suggests that early agricultural populations experienced "
            "declining health compared to their hunter-gatherer predecessors. Skeletal "
            "remains show increased rates of dental disease, nutritional deficiencies, "
            "and infectious illness — consequences of a diet dominated by a few starchy "
            "crops and of living in close quarters with domesticated animals. The "
            "transition to agriculture thus represents a complex trade-off between "
            "population growth and individual well-being, one whose implications "
            "continue to be debated by scholars."
        ),
    },
    {
        "id": "psychology_memory",
        "title": "The Constructive Nature of Memory",
        "text": (
            "Traditional conceptions of memory as a faithful recording of experience "
            "have been largely abandoned by cognitive psychologists in favor of a "
            "constructive model. According to this view, memories are not stored as "
            "complete, unalterable representations but are instead reconstructed each "
            "time they are recalled. This reconstruction process is inherently "
            "creative: it draws on stored fragments of experience, general knowledge, "
            "expectations, and even current emotional states to produce a coherent "
            "narrative that may diverge significantly from the original event.\n\n"
            "The pioneering work of Sir Frederic Bartlett in the 1930s provided early "
            "evidence for this constructive view. In his classic experiments, Bartlett "
            "asked British participants to read and later recall a Native American folk "
            "tale unfamiliar to them. Over successive retellings, participants "
            "systematically altered the story: unfamiliar elements were omitted or "
            "replaced with culturally familiar ones, causal relationships were added "
            "where none existed in the original, and the narrative was progressively "
            "rationalized to conform to the participants' expectations.\n\n"
            "Modern neuroscience has substantially confirmed and extended Bartlett's "
            "findings. Brain imaging studies demonstrate that remembering and imagining "
            "activate largely overlapping neural networks, particularly in the "
            "hippocampus and prefrontal cortex. This neuroanatomical overlap suggests "
            "that the same cognitive machinery that allows us to construct plausible "
            "future scenarios also shapes our retrieval of past experiences. Each act "
            "of recall effectively creates a new memory trace that incorporates both "
            "the original experience and the conditions of its retrieval.\n\n"
            "The implications of this research extend well beyond academic psychology. "
            "The constructive nature of memory has profound consequences for the legal "
            "system, where eyewitness testimony has traditionally been treated as "
            "reliable evidence. Elizabeth Loftus's influential studies on the "
            "misinformation effect demonstrated that exposure to misleading information "
            "after an event can fundamentally alter a person's memory of that event. "
            "In one representative experiment, participants who viewed a traffic "
            "accident and were later asked how fast the cars were going when they "
            '"smashed" into each other gave significantly higher speed estimates than '
            'those asked about cars that "contacted" each other — and were more '
            "likely to falsely remember seeing broken glass at the scene."
        ),
    },
]

# Expected question types per passage (what a good quiz should include).
EXPECTED_TYPES = {"factual", "inference", "vocab", "rhetorical", "negative_factual"}


def _make_content(passage: dict) -> ContentItem:
    return ContentItem(
        id=1,
        user_id=1,
        source_type=SourceType.CHANNEL,
        source_ref="eval",
        external_id=passage["id"],
        content_type=ContentType.ARTICLE,
        title=passage["title"],
        body_text=passage["text"],
        fetched_at=datetime.now(UTC),
    )


def _get_llm():
    """Get the appropriate LLM client based on configuration."""
    backend = os.environ.get("LLM_BACKEND", "stub").lower()
    if backend == "ollama":
        from tutor.adapters.llm.ollama import OllamaLLMClient

        return OllamaLLMClient(
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
            model=os.environ.get("OLLAMA_MODEL", "glm-5:cloud"),
        )
    return StubLLMClient()


# ---------------------------------------------------------------------------
# Structural tests (always run, CI-safe)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("passage", PASSAGES, ids=[p["id"] for p in PASSAGES])
async def test_quiz_structure(passage):
    """Every quiz must have valid options and correct_index."""
    content = _make_content(passage)
    llm = _get_llm()
    quiz = await build_reading_quiz(llm, content, n=4)

    assert len(quiz) >= 1, "Quiz must have at least 1 question"
    for q in quiz:
        assert len(q.options) == 4, f"Expected 4 options, got {len(q.options)}"
        assert 0 <= q.correct_index < 4, f"correct_index {q.correct_index} out of range"
        assert q.prompt.strip(), "Question prompt must not be empty"
        assert q.explanation.strip(), "Explanation must not be empty"


# ---------------------------------------------------------------------------
# Quality evals (only run against real LLM)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("passage", PASSAGES, ids=[p["id"] for p in PASSAGES])
async def test_quiz_type_diversity(passage):
    """Quiz should include diverse question types (LLM-only eval)."""
    if os.environ.get("LLM_BACKEND", "stub").lower() == "stub":
        pytest.skip("Stub LLM does not produce question_type labels")

    content = _make_content(passage)
    llm = _get_llm()
    quiz = await build_reading_quiz(llm, content, n=5)

    # Check that we get at least 3 distinct question types.
    types = {q.question_type for q in quiz if hasattr(q, "question_type") and q.question_type}
    # The stub doesn't set question_type, so this only works with real LLM.
    assert len(types) >= 3, f"Expected >= 3 question types, got {types}"


async def test_quiz_passage_alignment():
    """Questions must reference the passage content, not generic trivia."""
    content = _make_content(PASSAGES[0])  # climate passage
    llm = _get_llm()
    quiz = await build_reading_quiz(llm, content, n=3)

    # Each question prompt should contain at least one word from the passage.
    passage_words = set(PASSAGES[0]["text"].lower().split())
    for q in quiz:
        q_words = set(q.prompt.lower().split())
        overlap = q_words & passage_words
        assert len(overlap) >= 2, f"Question seems unrelated to passage: '{q.prompt[:80]}...'"


async def test_no_absurd_distractors():
    """Distractors should not be obviously absurd or off-topic."""
    content = _make_content(PASSAGES[1])  # agriculture passage
    llm = _get_llm()
    quiz = await build_reading_quiz(llm, content, n=3)

    # Check that all options are at least plausible English sentences.
    for q in quiz:
        for i, opt in enumerate(q.options):
            assert len(opt) > 10, f"Option {i} too short to be plausible: '{opt}'"
            # Should not contain placeholder text.
            assert "stub" not in opt.lower(), f"Stub placeholder in option: '{opt}'"


# ---------------------------------------------------------------------------
# LLM-as-judge evaluation (detailed quality report)
# ---------------------------------------------------------------------------


_JUDGE_SYSTEM = (
    "You are an expert TOEFL question quality evaluator. Rate each question "
    "on a 1-5 scale for each dimension:\n"
    "- relevance: Does the question test understanding of the passage?\n"
    "- distractor_quality: Are the wrong answers plausible but clearly wrong?\n"
    "- toefl_authenticity: Does this look like a real ETS TOEFL question?\n"
    "- clarity: Is the question stem unambiguous?\n\n"
    "Return a JSON object with scores and brief justifications."
)


async def test_llm_judge_quality_report():
    """Generate a quiz and have the LLM judge its quality.
    Results are written to tests/eval_results.json for tracking.
    """
    if os.environ.get("LLM_BACKEND", "stub").lower() == "stub":
        pytest.skip("Stub LLM — no quality eval needed")

    content = _make_content(PASSAGES[0])  # climate passage
    llm = _get_llm()

    # Generate quiz.
    quiz = await build_reading_quiz(llm, content, n=4)

    # Build judge prompt.
    questions_text = "\n\n".join(
        f"Q{i + 1} ({getattr(q, 'question_type', '?')}): {q.prompt}\n"
        + "\n".join(f"  {chr(65 + j)}) {opt}" for j, opt in enumerate(q.options))
        + f"\n  Correct: {chr(65 + q.correct_index)}\n"
        + f"  Explanation: {q.explanation}"
        for i, q in enumerate(quiz)
    )

    judge_prompt = (
        f"PASSAGE:\n{PASSAGES[0]['text'][:500]}...\n\n"
        f"QUESTIONS:\n{questions_text}\n\n"
        "Rate each question 1-5 on: relevance, distractor_quality, "
        "toefl_authenticity, clarity. Return JSON."
    )

    # Run judge — use complete() since the judge returns free-form analysis.
    judge_response = await llm.complete(_JUDGE_SYSTEM, judge_prompt)

    # Write results.
    results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "passage": PASSAGES[0]["id"],
        "n_questions": len(quiz),
        "questions": [
            {
                "type": getattr(q, "question_type", "unknown"),
                "prompt": q.prompt[:100],
                "n_options": len(q.options),
                "correct_index": q.correct_index,
            }
            for q in quiz
        ],
        "judge_response": judge_response[:2000],
    }

    results_path = Path(__file__).parent / "eval_results.json"
    # Append to existing results.
    existing = []
    if results_path.exists():
        try:
            existing = json.loads(results_path.read_text())
        except (json.JSONDecodeError, ValueError):
            existing = []
    existing.append(results)
    results_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))

    # Basic assertion — at least the quiz was generated.
    assert len(quiz) >= 3, f"Expected >= 3 questions, got {len(quiz)}"
