"""Reading-comprehension quiz generation — the one LLM call on the graded path.

`complete_json` returns a validated `ReadingQuizPayload`; we then drop any
question whose `correct_index` is out of range, so a malformed model response
can never produce an ungradeable quiz.
"""

from __future__ import annotations

from tutor.domain.models import ContentItem, QuizQuestion
from tutor.eval.schemas import ReadingQuizPayload
from tutor.interfaces.llm import LLMClient

_QUESTION_TYPES = (
    "factual",
    "negative_factual",
    "inference",
    "rhetorical",
    "vocab",
    "simplification",
    "summary",
)

_SYSTEM = (
    "You are an expert TOEFL iBT Reading section question writer. Your questions "
    "must be indistinguishable from real ETS-published TOEFL questions in style, "
    "difficulty, and trap design.\n\n"
    "QUESTION TYPES (label each question with its type):\n\n"
    '1. factual — "According to the passage, ...", "The author states that ..."\n'
    "   Tests explicit information stated in 1-2 sentences. The correct answer "
    "   paraphrases the passage; distractors use passage words but distort meaning.\n\n"
    '2. negative_factual — "All of the following are mentioned EXCEPT ...",\n'
    '   "Which of the following is NOT stated in the passage?"\n'
    "   Three options ARE in the passage, one is not (or is contradicted). "
    '   The "not" makes this harder — students must check each option.\n\n'
    '3. inference — "What can be inferred from paragraph X?",\n'
    '   "The author implies that ...", "Which of the following can be '
    '   concluded about X?"\n'
    "   The answer is NOT directly stated but is strongly supported by the "
    "   text. Distractors are plausible but go beyond what the text supports.\n\n"
    '4. rhetorical — "Why does the author mention X?", "The author discusses '
    '   X in order to ...", "What purpose does paragraph X serve?"\n'
    "   Tests understanding of the author's intent, not the content itself. "
    '   Correct answer uses language like "to illustrate", "to challenge", '
    '   "to provide evidence for", "to contrast with".\n\n'
    "5. vocab — \"The word 'X' in the passage is closest in meaning to ...\",\n"
    "   \"As used in paragraph X, the word 'Y' most likely means ...\"\n"
    "   Tests academic vocabulary (Zipf 3-5) in context. All 4 options must be "
    "   plausible meanings of the word; the correct one fits the specific context.\n\n"
    '6. simplification — "Which of the following best expresses the meaning '
    '   of the highlighted sentence?"\n'
    "   The correct answer preserves ALL essential meaning. Distractors: omit "
    "   a key idea, reverse a relationship, or add unsupported information.\n\n"
    '7. summary — "An introductory sentence for a brief summary of the passage '
    '   is provided. Complete the summary by selecting the 3 key ideas."\n'
    "   This is a MULTI-SELECT question: provide exactly 6 options and set "
    '   "correct_indices" to the THREE 0-based indices that best summarize the '
    "   passage (major ideas, not minor details). The 3 wrong options state minor "
    "   details, are not mentioned, or contradict the passage. For this type set "
    '   "correct_index" to any one of the correct indices (it is ignored when '
    '   "correct_indices" is present).\n\n'
    "DISTRACTOR CONSTRUCTION RULES:\n"
    "- NEVER make distractors obviously absurd, off-topic, or comically wrong.\n"
    "- Each distractor must exploit a specific misreading:\n"
    "  • Uses words from the passage but in a different context\n"
    "  • States something true from the passage but doesn't answer THIS question\n"
    "  • Overgeneralizes or uses extreme language (always, never, all, none)\n"
    "  • Reverses a cause-effect or compare-contrast relationship\n"
    "  • Is a reasonable inference but not supported by the specific paragraph\n"
    "- For vocab questions: all 4 options must be real English words that could "
    "plausibly mean the target word.\n\n"
    "FORMATTING:\n"
    '- Use formal academic register ("The author", "According to the passage")\n'
    "- Questions must be answerable from the passage alone — no outside knowledge\n"
    "- Each question needs a question_type label from: " + ", ".join(_QUESTION_TYPES)
)


def _user_prompt(passage: str, n: int, recall_hint: str = "") -> str:
    base = (
        f"Write exactly {n} TOEFL reading-comprehension questions for this passage. "
        f"Each question must have exactly 4 options (A-D), one correct answer, "
        f"a question_type label, and a short explanation.\n\n"
        f"QUESTION TYPE DISTRIBUTION (for {n} questions):\n"
    )
    if n <= 2:
        base += "- Pick the 2 most natural types for this passage.\n"
    elif n <= 4:
        base += (
            "- Include at least 1 vocab-in-context and 1 inference question.\n"
            "- Fill remaining with factual, rhetorical, or negative_factual.\n"
        )
    else:
        base += (
            "- Include at least 1 vocab, 1 inference, 1 factual, 1 rhetorical, "
            "1 negative_factual, 1 simplification.\n"
            "- Include EXACTLY 1 summary question (multi-select, 6 options, "
            "3 correct via correct_indices) as the LAST question.\n"
            "- Fill any remaining slots with more factual/inference/vocab questions.\n"
        )
    base += f"\nPASSAGE:\n{passage}"
    return f"{base}\n\n{recall_hint}" if recall_hint else base


def _to_question(q: object) -> QuizQuestion | None:
    """Validate a payload question and convert it to a domain QuizQuestion.

    Drops anything ungradeable: a single-select with an out-of-range key, or a
    multi-select whose `correct_indices` are empty or out of range.
    """
    n_opts = len(q.options)  # type: ignore[attr-defined]
    raw_multi = list(getattr(q, "correct_indices", []) or [])
    multi = sorted({i for i in raw_multi if 0 <= i < n_opts})
    if raw_multi:  # intended as multi-select
        if len(multi) < 2:
            return None
        return QuizQuestion(
            prompt=q.prompt,  # type: ignore[attr-defined]
            options=q.options,  # type: ignore[attr-defined]
            correct_index=multi[0],
            correct_indices=multi,
            explanation=q.explanation,  # type: ignore[attr-defined]
            question_type=getattr(q, "question_type", ""),
        )
    if 0 <= q.correct_index < n_opts:  # type: ignore[attr-defined]
        return QuizQuestion(
            prompt=q.prompt,  # type: ignore[attr-defined]
            options=q.options,  # type: ignore[attr-defined]
            correct_index=q.correct_index,  # type: ignore[attr-defined]
            explanation=q.explanation,  # type: ignore[attr-defined]
            question_type=getattr(q, "question_type", ""),
        )
    return None


async def build_reading_quiz(
    llm: LLMClient,
    content: ContentItem,
    n: int = 3,
    *,
    system: str | None = None,
    recall_hint: str = "",
) -> list[QuizQuestion]:
    payload = await llm.complete_json(
        system or _SYSTEM, _user_prompt(content.body_text, n, recall_hint), ReadingQuizPayload
    )
    questions: list[QuizQuestion] = []
    for q in payload.questions:
        converted = _to_question(q)
        if converted is not None:
            questions.append(converted)
    return questions


_LISTENING_SYSTEM = (
    "You are a TOEFL listening-comprehension question writer. The passage below is "
    "a TRANSCRIPT of a spoken passage (podcast/lecture), not a written text. Write "
    "questions that match the real TOEFL iBT Listening section format and difficulty "
    "(C1 level).\n\n"
    "Question types to include (pick the most natural ones for the content):\n"
    "1. Gist-Content — what is the main topic/idea of the talk\n"
    "2. Gist-Purpose — why does the speaker give this talk/mention this\n"
    "3. Detail — about specific facts or examples mentioned\n"
    "4. Function — why does the speaker say a particular phrase (pragmatic purpose)\n"
    "5. Attitude — what is the speaker's opinion, feeling, or stance\n"
    "6. Connecting Content — how ideas relate, what the speaker implies about connections\n"
    "7. Inference — what can be reasonably concluded from what the speaker says\n\n"
    "Rules:\n"
    "- Refer to 'the speaker' or 'the lecturer', NOT 'the author'.\n"
    "- Exactly one option is unambiguously correct.\n"
    "- Distractors must be plausible — exploit common mishearings or "
    "misinterpretations of spoken language.\n"
    "- Questions must be answerable from the transcript alone.\n"
    "- Use conversational register matching real TOEFL listening questions.\n"
    "- For detail questions, test information that a listener would need to note, "
    "not trivial surface facts."
)


def _listening_prompt(transcript: str, n: int, recall_hint: str = "") -> str:
    base = (
        f"Write exactly {n} TOEFL listening-comprehension multiple-choice questions "
        f"about the transcript below. Each question must have exactly 4 options (A-D), "
        f"one correct, and a short explanation of why the correct answer is right.\n\n"
        f"Distribute question types naturally across: Gist-Content, Gist-Purpose, "
        f"Detail, Function, Attitude, and Inference. Include at least 1 Gist-Content "
        f"and 1 Detail question if n >= 3.\n\n"
        f"TRANSCRIPT:\n{transcript}"
    )
    return f"{base}\n\n{recall_hint}" if recall_hint else base


async def build_listening_quiz(
    llm: LLMClient,
    content: ContentItem,
    n: int = 3,
    *,
    system: str | None = None,
    recall_hint: str = "",
) -> list[QuizQuestion]:
    """Build a TOEFL listening-comprehension quiz from a podcast transcript."""
    payload = await llm.complete_json(
        system or _LISTENING_SYSTEM,
        _listening_prompt(content.body_text, n, recall_hint),
        ReadingQuizPayload,  # same schema: questions with options
    )
    questions: list[QuizQuestion] = []
    for q in payload.questions:
        converted = _to_question(q)
        if converted is not None:
            questions.append(converted)
    return questions
