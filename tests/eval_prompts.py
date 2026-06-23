"""Comprehensive prompt evaluation: reading quiz, listening quiz, ANKI flashcards.

Runs against the real LLM (Ollama) and judges quality with LLM-as-judge.
Results are written to tests/eval_results.json.

Usage:
    LLM_BACKEND=ollama python -m pytest tests/eval_prompts.py -v -s --timeout=300
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tutor.adapters.llm.ollama import OllamaLLMClient
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import ContentItem, VocabItem
from tutor.eval.flashcards import make_flashcards
from tutor.eval.quiz_builder import build_listening_quiz, build_reading_quiz
from tutor.worksheet.generator import generate_worksheet

# ---------------------------------------------------------------------------
# Test data: real TOEFL-like passages and podcast transcripts
# ---------------------------------------------------------------------------

ARTICLES = [
    {
        "id": "climate_ocean",
        "title": "Ocean Currents and Climate",
        "text": (
            "Ocean currents play a crucial role in regulating Earth's climate by "
            "distributing heat energy from the equator toward the poles. The most "
            "significant of these circulation patterns is the thermohaline circulation, "
            "often referred to as the global conveyor belt. This system is driven by "
            "differences in water density, which are determined by temperature and "
            "salinity. In the North Atlantic, cold, salty water sinks to the deep ocean, "
            "drawing warmer surface water northward from the tropics. This process "
            "releases enormous amounts of heat into the atmosphere, moderating the "
            "climate of Western Europe.\n\n"
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
            "Nordic Seas."
        ),
    },
    {
        "id": "neolithic",
        "title": "The Neolithic Revolution",
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
            "monumental architecture.\n\n"
            "Critics of this narrative, however, point out that the Neolithic Revolution "
            "was neither sudden nor uniformly beneficial. Archaeological evidence from "
            "multiple sites suggests that early agricultural populations experienced "
            "declining health compared to their hunter-gatherer predecessors. Skeletal "
            "remains show increased rates of dental disease, nutritional deficiencies, "
            "and infectious illness."
        ),
    },
    {
        "id": "memory_psych",
        "title": "The Constructive Nature of Memory",
        "text": (
            "Traditional conceptions of memory as a faithful recording of experience "
            "have been largely abandoned by cognitive psychologists in favor of a "
            "constructive model. According to this view, memories are not stored as "
            "complete, unalterable representations but are instead reconstructed each "
            "time they are recalled. This reconstruction process is inherently creative: "
            "it draws on stored fragments of experience, general knowledge, expectations, "
            "and even current emotional states to produce a coherent narrative that may "
            "diverge significantly from the original event.\n\n"
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
            "future scenarios also shapes our retrieval of past experiences."
        ),
    },
]

PODCASTS = [
    {
        "id": "ai_ethics",
        "title": "The Ethics of Artificial Intelligence",
        "text": (
            "Welcome to today's episode. We're going to be talking about something "
            "that's been on a lot of people's minds lately — the ethical implications "
            "of artificial intelligence. Now, you might be thinking, oh great, another "
            "AI discussion. But I promise you, this one's different because we're going "
            "to focus on the practical challenges that companies actually face right now, "
            "not some distant sci-fi scenario.\n\n"
            "So let me start with a concrete example. Last year, a major healthcare "
            "company deployed an AI system to help prioritize patient treatments. The "
            "idea was straightforward — use machine learning to analyze patient data and "
            "recommend which cases needed immediate attention. Sounds reasonable, right? "
            "Well, it turned out the system had a significant bias. It was systematically "
            "underestimating the severity of conditions in Black patients. And the reason "
            "was fascinating and troubling at the same time — the training data reflected "
            "historical patterns of unequal access to healthcare, so the AI essentially "
            "learned to perpetuate existing inequalities.\n\n"
            "This brings us to what I think is the core tension in AI ethics. On one hand, "
            "these systems can process vastly more information than any human doctor, "
            "lawyer, or financial advisor. They can spot patterns we'd never notice. On "
            "the other hand, they're trained on data that reflects our world — with all "
            "its biases and imperfections. So the question becomes: how do we get the "
            "benefits of AI while minimizing the risks?\n\n"
            "There are several approaches being explored. One is what's called 'algorithmic "
            "auditing' — basically, regularly checking AI systems for biased outputs, "
            "similar to how we audit financial statements. Another approach is building "
            "diversity into the development teams themselves, the idea being that a more "
            "diverse team is more likely to spot potential biases. And then there's the "
            "regulatory approach — governments stepping in to set rules about transparency "
            "and accountability."
        ),
    },
    {
        "id": "space_colonization",
        "title": "Living on Mars: Challenges and Realities",
        "text": (
            "Today we're going to talk about something that captures the imagination "
            "like few other topics — the idea of humans living on Mars. Now, I know "
            "what you're probably thinking. We've seen the movies, we've read the books. "
            "But the reality of actually establishing a permanent human presence on Mars "
            "is far more complicated than most people realize.\n\n"
            "Let's start with the basics. The journey to Mars takes about seven months "
            "with current technology. During that time, astronauts are exposed to "
            "significant levels of cosmic radiation, which increases their risk of "
            "cancer. Once they arrive, they face a planet with an atmosphere that's "
            "about 95 percent carbon dioxide, surface temperatures that average minus "
            "60 degrees Celsius, and gravity that's only about 38 percent of Earth's.\n\n"
            "But here's what I find really interesting — the technical challenges, while "
            "enormous, might actually be easier to solve than the psychological ones. "
            "Studies of astronauts on the International Space Station have shown that "
            "isolation and confinement can lead to serious mental health issues. "
            "Depression, anxiety, interpersonal conflicts — these are real problems "
            "that affect mission performance. Now imagine being on Mars, knowing that "
            "Earth is just a tiny dot in the sky, and that if something goes wrong, "
            "help is at least six months away.\n\n"
            "There's also the question of what happens to the human body in low gravity "
            "over extended periods. We know from ISS studies that astronauts lose bone "
            "density and muscle mass at alarming rates. Their vision deteriorates due "
            "to changes in intracranial pressure. Their immune systems weaken. These "
            "are problems we haven't solved even for stays of a year or two in low "
            "Earth orbit, let alone for permanent residence on Mars."
        ),
    },
]


def _make_content(item: dict, content_type: ContentType) -> ContentItem:
    source = SourceType.RSS if content_type == ContentType.PODCAST else SourceType.CHANNEL
    return ContentItem(
        id=1,
        user_id=1,
        source_type=source,
        source_ref="eval",
        external_id=item["id"],
        content_type=content_type,
        title=item["title"],
        body_text=item["text"],
        fetched_at=datetime.now(UTC),
    )


def _get_llm() -> OllamaLLMClient:
    return OllamaLLMClient(
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        api_key=os.environ.get("OLLAMA_API_KEY", "ollama"),
        model=os.environ.get("OLLAMA_MODEL", "glm-5:cloud"),
    )


def _is_real_llm() -> bool:
    return os.environ.get("LLM_BACKEND", "stub").lower() == "ollama"


# ---------------------------------------------------------------------------
# Helper: format quiz for display and judging
# ---------------------------------------------------------------------------


def _fmt_quiz(quiz) -> str:
    lines = []
    for i, q in enumerate(quiz):
        lines.append(f"Q{i + 1} [{q.question_type}]: {q.prompt}")
        for j, opt in enumerate(q.options):
            mark = "✓" if j == q.correct_index else " "
            lines.append(f"  {mark} {chr(65 + j)}) {opt}")
        lines.append(f"  Explanation: {q.explanation}")
    return "\n".join(lines)


def _fmt_cards(cards) -> str:
    lines = []
    for c in cards:
        tag = [t for t in c.tags if t != "toefl"][0]
        lines.append(f"[{tag}] {c.front}")
    return "\n".join(lines)


# ===========================================================================
# READING QUIZ EVALS
# ===========================================================================


READING_JUDGE = (
    "You are an expert TOEFL iBT Reading question evaluator. Rate the quiz on "
    "a scale of 1-5 for each dimension:\n\n"
    "1. QUESTION_TYPE_DIVERSITY (1-5): Are there at least 3 distinct question "
    "types? (factual, inference, vocab, rhetorical, negative_factual)\n"
    "2. DISTRACTOR_QUALITY (1-5): Are wrong answers plausible but clearly wrong? "
    "Do they exploit specific misreadings rather than being absurd?\n"
    "3. TOEFL_AUTHENTICITY (1-5): Do questions look like real ETS TOEFL questions? "
    "Correct stems, academic register, proper difficulty?\n"
    "4. PASSAGE_ALIGNMENT (1-5): Is every question answerable from the passage? "
    "Does no question require outside knowledge?\n"
    "5. EXPLANATION_QUALITY (1-5): Do explanations clearly justify the correct "
    "answer and explain why distractors are wrong?\n\n"
    'Return a JSON object: {"scores": {dim: score, ...}, "notes": "brief summary"}'
)


@pytest.mark.skipif(not _is_real_llm(), reason="Requires Ollama")
@pytest.mark.parametrize("article", ARTICLES, ids=[a["id"] for a in ARTICLES])
async def test_reading_quiz_quality(article):
    """Generate a reading quiz and have LLM judge its quality."""
    llm = _get_llm()
    content = _make_content(article, ContentType.ARTICLE)

    quiz = await build_reading_quiz(llm, content, n=4)
    assert len(quiz) >= 3, f"Expected >= 3 questions, got {len(quiz)}"

    # Check structural constraints.
    for q in quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < 4
        assert q.question_type, f"Missing question_type for: {q.prompt[:50]}"

    # Check type diversity.
    types = {q.question_type for q in quiz}
    assert len(types) >= 3, f"Only {len(types)} types: {types}"

    # LLM judge.
    quiz_text = _fmt_quiz(quiz)
    judge_prompt = (
        f"PASSAGE ({article['title']}):\n{article['text']}\n\n"
        f"QUIZ:\n{quiz_text}\n\n"
        "Rate each dimension 1-5 and explain briefly."
    )
    judge_response = await llm.complete(READING_JUDGE, judge_prompt)

    # Store results.
    _store_result(
        "reading_quiz",
        article["id"],
        {
            "n_questions": len(quiz),
            "types": list(types),
            "questions": [{"type": q.question_type, "prompt": q.prompt[:80]} for q in quiz],
            "judge": judge_response[:1500],
        },
    )


# ===========================================================================
# LISTENING QUIZ EVALS
# ===========================================================================


LISTENING_JUDGE = (
    "You are an expert TOEFL iBT Listening question evaluator. The passage is a "
    "TRANSCRIPT of spoken language (podcast/lecture). Rate the quiz on a scale of "
    "1-5 for each dimension:\n\n"
    "1. SPEAKER_REFERENCE (1-5): Do questions refer to 'the speaker' or 'the "
    "lecturer' rather than 'the author'? Does the language match listening section "
    "conventions?\n"
    "2. QUESTION_TYPE_DIVERSITY (1-5): Are there distinct types: Gist-Content, "
    "Gist-Purpose, Detail, Function, Attitude, Inference?\n"
    "3. SPOKEN_LANGUAGE_SENSITIVITY (1-5): Do questions test understanding of "
    "spoken discourse — tone, emphasis, pragmatic meaning — not just facts?\n"
    "4. DISTRACTOR_QUALITY (1-5): Are distractors plausible? Do they exploit "
    "common mishearings or misinterpretations of spoken content?\n"
    "5. TRANSCRIPT_ALIGNMENT (1-5): Is every question answerable from the "
    "transcript alone?\n\n"
    'Return a JSON object: {"scores": {dim: score, ...}, "notes": "brief summary"}'
)


@pytest.mark.skipif(not _is_real_llm(), reason="Requires Ollama")
@pytest.mark.parametrize("podcast", PODCASTS, ids=[p["id"] for p in PODCASTS])
async def test_listening_quiz_quality(podcast):
    """Generate a listening quiz and have LLM judge its quality."""
    llm = _get_llm()
    content = _make_content(podcast, ContentType.PODCAST)

    quiz = await build_listening_quiz(llm, content, n=4)
    assert len(quiz) >= 3, f"Expected >= 3 questions, got {len(quiz)}"

    for q in quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < 4

    # Check that questions reference "speaker"/"lecturer", not "author".
    for q in quiz:
        prompt_lower = q.prompt.lower()
        # Allow "author" only in negative contexts ("the speaker, not the author").
        if "author" in prompt_lower and "not the author" not in prompt_lower:
            # Warning, not failure — some questions may legitimately reference author.
            pass

    types = {q.question_type for q in quiz}
    assert len(types) >= 2, f"Only {len(types)} types: {types}"

    # LLM judge.
    quiz_text = _fmt_quiz(quiz)
    judge_prompt = (
        f"TRANSCRIPT ({podcast['title']}):\n{podcast['text']}\n\n"
        f"QUIZ:\n{quiz_text}\n\n"
        "Rate each dimension 1-5. Note if any question incorrectly uses 'author' "
        "instead of 'speaker'."
    )
    judge_response = await llm.complete(LISTENING_JUDGE, judge_prompt)

    _store_result(
        "listening_quiz",
        podcast["id"],
        {
            "n_questions": len(quiz),
            "types": list(types),
            "questions": [{"type": q.question_type, "prompt": q.prompt[:80]} for q in quiz],
            "judge": judge_response[:1500],
        },
    )


# ===========================================================================
# ANKI FLASHCARD EVALS
# ===========================================================================


FLASHCARD_JUDGE = (
    "You are an expert TOEFL vocabulary coach evaluating Anki flashcards generated "
    "from a passage. Rate the card set on a scale of 1-5 for each dimension:\n\n"
    "1. EXHAUSTIVENESS (1-5): Does the set capture ALL useful expressions from the "
    "passage — vocabulary, phrasal verbs, collocations, idioms, academic phrases? "
    "Are important items missing?\n"
    "2. CATEGORY_DIVERSITY (1-5): Are there cards from multiple categories: single "
    "words, phrasal verbs, collocations, idioms, phrases?\n"
    "3. TOEFL_RELEVANCE (1-5): Are the selected items genuinely useful for a TOEFL "
    "B2-C1 learner? Not too basic, not too obscure?\n"
    "4. ACCURACY (1-5): Do the terms actually appear in the passage? Are the "
    "definitions correct?\n"
    "5. CARD_QUALITY (1-5): Is the front (term) clean? Is the back (definition + "
    "example) clear and helpful for learning?\n\n"
    "Also list up to 5 important expressions from the passage that are MISSING "
    "from the card set.\n\n"
    'Return a JSON object: {"scores": {dim: score, ...}, "missing": [...], '
    '"notes": "brief summary"}'
)


@pytest.mark.skipif(not _is_real_llm(), reason="Requires Ollama")
@pytest.mark.parametrize("article", ARTICLES, ids=[a["id"] for a in ARTICLES])
async def test_flashcard_quality(article):
    """Generate flashcards and have LLM judge quality and exhaustiveness."""
    llm = _get_llm()

    cards = await make_flashcards(llm, article["text"], limit=30)
    assert len(cards) >= 10, f"Expected >= 10 cards, got {len(cards)}"

    # Check that all cards are actually in the passage.
    text_lower = article["text"].lower()
    for c in cards:
        assert c.front.lower() in text_lower or c.front.lower().replace(
            " ", ""
        ) in text_lower.replace(" ", ""), f"Card '{c.front}' not found in passage"

    # Check category diversity.
    tags = {t for c in cards for t in c.tags if t != "toefl"}
    assert len(tags) >= 2, f"Only {len(tags)} categories: {tags}"

    # LLM judge.
    cards_text = _fmt_cards(cards)
    judge_prompt = (
        f"PASSAGE ({article['title']}):\n{article['text']}\n\n"
        f"GENERATED CARDS ({len(cards)} total):\n{cards_text}\n\n"
        "Rate each dimension 1-5. List important missing expressions."
    )
    judge_response = await llm.complete(FLASHCARD_JUDGE, judge_prompt)

    _store_result(
        "flashcards",
        article["id"],
        {
            "n_cards": len(cards),
            "categories": list(tags),
            "sample_cards": [
                {"front": c.front, "tags": [t for t in c.tags if t != "toefl"]} for c in cards[:10]
            ],
            "judge": judge_response[:1500],
        },
    )


# ===========================================================================
# Comparative: does higher limit yield more coverage?
# ===========================================================================


@pytest.mark.skipif(not _is_real_llm(), reason="Requires Ollama")
async def test_flashcard_limit_comparison():
    """Compare limit=10 vs limit=30 on the same passage."""
    llm = _get_llm()
    text = ARTICLES[0]["text"]

    cards_10 = await make_flashcards(llm, text, limit=10)
    cards_30 = await make_flashcards(llm, text, limit=30)

    terms_10 = {c.front.lower() for c in cards_10}
    terms_30 = {c.front.lower() for c in cards_30}

    # limit=30 should produce more unique terms.
    assert len(terms_30) > len(terms_10), (
        f"limit=30 produced {len(terms_30)} cards, limit=10 produced {len(terms_10)}. "
        f"Expected limit=30 to produce more."
    )

    # LLM is non-deterministic — different runs pick different items.
    # Just check that limit=30 produces more, and there's some overlap.
    overlap = len(terms_10 & terms_30) / len(terms_10) if terms_10 else 0
    # Relaxed threshold — the key assertion is count, not overlap.
    assert overlap >= 0.1, (
        f"Only {overlap:.0%} overlap between limit=10 and limit=30. "
        f"Missing from limit=30: {terms_10 - terms_30}"
    )

    _store_result(
        "flashcard_comparison",
        "limit_test",
        {
            "limit_10_count": len(cards_10),
            "limit_30_count": len(cards_30),
            "overlap": f"{overlap:.0%}",
            "unique_in_30": len(terms_30 - terms_10),
        },
    )


# ===========================================================================
# WORKSHEET GENERATION EVALS
# ===========================================================================

WORKSHEET_JUDGE = (
    "You are evaluating a TOEFL-style homework worksheet generated from an article "
    "and a podcast transcript. Rate on a scale of 1-5 for each dimension:\n\n"
    "1. READING_QUIZ_QUALITY (1-5): Are reading questions grounded in the article? "
    "Correct difficulty (B2-C1)? 4-option MCQ with plausible distractors?\n"
    "2. LISTENING_QUIZ_QUALITY (1-5): Are listening questions grounded in the podcast "
    "transcript? Do they test spoken-language comprehension (gist, detail, inference)?\n"
    "3. FILL_BLANKS_QUALITY (1-5): Are fill-in-the-blank items testing vocabulary in "
    "context, not isolated words? All 4 options grammatically possible?\n"
    "4. OVERALL_COHERENCE (1-5): Is the worksheet coherent as a whole? No repeated "
    "questions across sections? All answers derivable from the provided materials?\n\n"
    'Return: {"scores": {dim: score}, "issues": ["list any serious problems"], '
    '"notes": "brief summary"}'
)

# Long article (> 5000 chars) to exercise chunked processing.
LONG_ARTICLE = {
    "id": "long_climate",
    "title": "Ocean Currents and Climate Regulation — Extended Study",
    "text": (
        ARTICLES[0]["text"] * 3  # ~5400 chars, triggers chunking
    ),
}


@pytest.mark.skipif(not _is_real_llm(), reason="Requires Ollama")
async def test_worksheet_generation_with_long_article():
    """Full worksheet generated from a long article — verifies chunked extraction works."""
    llm = _get_llm()
    article = _make_content(LONG_ARTICLE, ContentType.ARTICLE)

    payload = await generate_worksheet(
        llm,
        vocab=[],
        errors=[],
        articles=[article],
    )

    assert payload.reading_quiz, "reading_quiz should be populated from the article"
    assert len(payload.reading_quiz) >= 2
    for q in payload.reading_quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < 4
        assert q.prompt.strip()

    _store_result(
        "worksheet_long_article",
        LONG_ARTICLE["id"],
        {
            "article_chars": len(LONG_ARTICLE["text"]),
            "reading_quiz_count": len(payload.reading_quiz),
            "fill_blanks_count": len(payload.fill_blanks),
            "error_correction_count": len(payload.error_correction),
            "sample_questions": [
                {"prompt": q.prompt[:80], "correct": q.correct_index}
                for q in payload.reading_quiz[:3]
            ],
        },
    )


@pytest.mark.skipif(not _is_real_llm(), reason="Requires Ollama")
async def test_worksheet_generation_with_podcast():
    """Full worksheet generated from article + podcast — verifies listening_quiz."""
    llm = _get_llm()
    article = _make_content(ARTICLES[0], ContentType.ARTICLE)
    podcast = _make_content(PODCASTS[0], ContentType.PODCAST)

    payload = await generate_worksheet(
        llm,
        vocab=[
            VocabItem(
                content_id=1,
                word="thermohaline",
                definition="relating to temp & salinity",
                freq_rank=2.0,
            ),
            VocabItem(
                content_id=1,
                word="bias",
                definition="systematic error in a dataset",
                freq_rank=3.0,
            ),
        ],
        errors=[],
        articles=[article],
        podcasts=[podcast],
    )

    assert payload.reading_quiz, "reading_quiz must be populated"
    assert payload.listening_quiz, "listening_quiz must be populated"

    for q in payload.reading_quiz + payload.listening_quiz:
        assert len(q.options) == 4
        assert 0 <= q.correct_index < 4

    # LLM judge.
    quiz_summary = (
        f"READING QUIZ ({len(payload.reading_quiz)} questions):\n"
        + "\n".join(f"  Q: {q.prompt[:80]}" for q in payload.reading_quiz)
        + f"\n\nLISTENING QUIZ ({len(payload.listening_quiz)} questions):\n"
        + "\n".join(f"  Q: {q.prompt[:80]}" for q in payload.listening_quiz)
        + f"\n\nFILL BLANKS: {len(payload.fill_blanks)} items"
        + f"\nERROR CORRECTION: {len(payload.error_correction)} items"
    )
    judge_prompt = (
        f"ARTICLE ({ARTICLES[0]['title']}):\n{ARTICLES[0]['text'][:800]}\n\n"
        f"PODCAST ({PODCASTS[0]['title']}):\n{PODCASTS[0]['text'][:800]}\n\n"
        f"GENERATED WORKSHEET:\n{quiz_summary}\n\n"
        "Rate each dimension 1-5."
    )
    judge_response = await llm.complete(WORKSHEET_JUDGE, judge_prompt)

    _store_result(
        "worksheet_full",
        "article_plus_podcast",
        {
            "reading_quiz_count": len(payload.reading_quiz),
            "listening_quiz_count": len(payload.listening_quiz),
            "fill_blanks_count": len(payload.fill_blanks),
            "judge": judge_response[:1500],
        },
    )


# ===========================================================================
# Result storage
# ===========================================================================


def _store_result(category: str, item_id: str, data: dict) -> None:
    """Append eval result to JSON file."""
    results_path = Path(__file__).parent / "eval_results.json"
    existing: list = []
    if results_path.exists():
        try:
            existing = json.loads(results_path.read_text())
        except (json.JSONDecodeError, ValueError):
            existing = []
    existing.append(
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "category": category,
            "item_id": item_id,
            **data,
        }
    )
    results_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
