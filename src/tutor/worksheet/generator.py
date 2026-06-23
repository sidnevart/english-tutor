"""Generate TOEFL-format evening worksheet from today's materials and errors.

The LLM produces a JSON payload with 5 exercise types, all grounded in the
learner's actual vocabulary, errors, and article content from today.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tutor.domain.models import ContentItem, VocabItem
from tutor.interfaces.llm import LLMClient


class FillBlank(BaseModel):
    sentence: str  # sentence with ________ blank
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    source_word: str = ""  # the vocabulary word being tested


class ErrorCorrection(BaseModel):
    sentence: str  # sentence with an error
    error_span: str  # the exact erroneous word/phrase
    correction: str  # the correct version
    rule: str  # grammar rule explanation


class SentenceTransform(BaseModel):
    original: str  # original sentence from the article
    model_answer: str  # acceptable paraphrase
    key_point: str  # the paraphrasing technique tested


class MiniReadingQuestion(BaseModel):
    prompt: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = ""


class MiniReading(BaseModel):
    passage_excerpt: str  # 150-200 words from today's article
    questions: list[MiniReadingQuestion] = Field(min_length=1)


class CollocationMatch(BaseModel):
    word: str
    correct_partner: str
    distractors: list[str] = Field(min_length=3, max_length=3)


class ReadingQuizItem(BaseModel):
    """Reading comprehension question from an article."""

    source_title: str = ""
    prompt: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = ""


class ListeningQuizItem(BaseModel):
    """Listening comprehension question from a podcast."""

    source_title: str = ""
    prompt: str
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = ""


class WorksheetPayload(BaseModel):
    fill_blanks: list[FillBlank] = Field(default_factory=list)
    error_correction: list[ErrorCorrection] = Field(default_factory=list)
    sentence_transform: list[SentenceTransform] = Field(default_factory=list)
    mini_reading: list[MiniReading] = Field(default_factory=list)
    collocation_match: list[CollocationMatch] = Field(default_factory=list)
    reading_quiz: list[ReadingQuizItem] = Field(default_factory=list)
    listening_quiz: list[ListeningQuizItem] = Field(default_factory=list)


_SYSTEM = (
    "You are a TOEFL iBT preparation exercise writer. Generate a set of "
    "practice exercises based on the learner's today materials and errors.\n\n"
    "EXERCISE TYPES:\n\n"
    "1. fill_blanks (5-7 items): Test vocabulary IN CONTEXT. Each sentence "
    "must have a clear blank (________) and 4 options where only one fits "
    "grammatically and semantically. Use the provided vocabulary words.\n\n"
    "2. error_correction (3-5 items): Use REAL errors from the learner's "
    "speaking sessions. If no errors provided, create sentences with common "
    "B2-C1 grammar traps (relative clauses, subject-verb agreement, article "
    "usage, preposition errors).\n\n"
    "3. sentence_transform (2-3 items): Take actual sentences from the "
    "article text. Ask the learner to paraphrase without changing meaning. "
    "Provide a model answer and the key technique (e.g., 'active → passive', "
    "'replace relative clause with participle').\n\n"
    "4. mini_reading (1 item): Select a 150-200 word excerpt from the article. "
    "Generate 3 TOEFL-format questions: 1 factual, 1 inference, 1 vocab-in-context.\n\n"
    "5. collocation_match (5 items): Pair vocabulary words with their natural "
    "academic collocations. Include 3 plausible distractors per word.\n\n"
    "6. reading_quiz (3 items per article): For each article provided, generate "
    "3 TOEFL iBT Reading section questions: 1 factual information, 1 inference, "
    "1 vocabulary-in-context. Use 4 multiple-choice options. Set source_title to "
    "the article title.\n\n"
    "7. listening_quiz (3 items per podcast): For each podcast transcript provided, "
    "generate 3 TOEFL iBT Listening section questions: 1 gist-content, 1 detail, "
    "1 inference. Use 4 multiple-choice options. Set source_title to the episode title.\n\n"
    "RULES:\n"
    "- All content must come from the provided input data\n"
    "- Difficulty: B2-C1 (TOEFL level)\n"
    "- All text in English\n"
    "- Be precise with correct_index values\n"
    "- If no articles provided, set reading_quiz to empty list\n"
    "- If no podcast transcripts provided, set listening_quiz to empty list"
)


def _user_prompt(
    vocab: list[VocabItem],
    errors: list[dict[str, str]],
    articles: list[ContentItem],
    podcasts: list[ContentItem] | None = None,
) -> str:
    parts: list[str] = []

    # Vocabulary.
    if vocab:
        vocab_lines = [f"  - {v.word} (freq {v.freq_rank:.1f}): {v.definition}" for v in vocab[:15]]
        parts.append("TODAY'S VOCABULARY:\n" + "\n".join(vocab_lines))
    else:
        parts.append("TODAY'S VOCABULARY: (none — generate from article text)")

    # Errors.
    if errors:
        error_lines = [
            f'  - [{e.get("error_type", "grammar")}] "{e["error_text"]}" → "{e["correction"]}"'
            for e in errors[:5]
        ]
        parts.append("\nTODAY'S SPEAKING ERRORS:\n" + "\n".join(error_lines))
    else:
        parts.append("\nTODAY'S SPEAKING ERRORS: (none — generate common B2-C1 grammar traps)")

    # Articles.
    for i, art in enumerate(articles[:2]):
        text = art.body_text.strip()[:2000]  # cap to avoid token overflow
        parts.append(f"\nARTICLE {i + 1} ({art.title or 'Untitled'}):\n{text}")

    if not articles:
        parts.append("\nARTICLES: (none available)")

    # Podcast transcripts.
    if podcasts:
        for i, pod in enumerate(podcasts[:2]):
            text = pod.body_text.strip()[:2000]
            parts.append(f"\nPODCAST TRANSCRIPT {i + 1} ({pod.title or 'Untitled'}):\n{text}")
    else:
        parts.append("\nPODCAST TRANSCRIPTS: (none available)")

    return "\n".join(parts)


async def generate_worksheet(
    llm: LLMClient,
    vocab: list[VocabItem],
    errors: list[dict[str, str]],
    articles: list[ContentItem],
    podcasts: list[ContentItem] | None = None,
) -> WorksheetPayload:
    """Generate a complete worksheet from today's data."""
    user = _user_prompt(vocab, errors, articles, podcasts)
    return await llm.complete_json(_SYSTEM, user, WorksheetPayload)


def worksheet_to_json(payload: WorksheetPayload) -> str:
    """Serialize worksheet payload to JSON string for DB storage."""
    return payload.model_dump_json(indent=2)


def worksheet_from_json(data: str) -> WorksheetPayload:
    """Deserialize worksheet payload from JSON string."""
    return WorksheetPayload.model_validate_json(data)
