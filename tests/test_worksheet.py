"""Tests for the evening worksheet pipeline: generator, renderer, parser, grader."""

from __future__ import annotations

from datetime import UTC, datetime

from tutor.adapters.llm.stub import StubLLMClient
from tutor.domain.enums import ContentType, SourceType
from tutor.domain.models import ContentItem, VocabItem
from tutor.worksheet.generator import (
    _PASS_THROUGH_LIMIT,
    WorksheetPayload,
    _extract_chunks,
    _prepare_text,
    generate_worksheet,
    worksheet_from_json,
    worksheet_to_json,
)
from tutor.worksheet.parser import (
    normalize_letter,
    parse_collocation_matches,
    parse_error_corrections,
    parse_fill_blanks,
    parse_sentence_transforms,
    parse_worksheet_answers,
)
from tutor.worksheet.renderer import render_worksheet_md

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _vocab() -> list[VocabItem]:
    return [
        VocabItem(
            content_id=1,
            word="thermohaline",
            definition="relating to temperature and salinity",
            freq_rank=2.5,
        ),
        VocabItem(content_id=1, word="circulation", definition="movement in a loop", freq_rank=4.0),
        VocabItem(content_id=1, word="profound", definition="very great or intense", freq_rank=4.5),
    ]


def _errors() -> list[dict[str, str]]:
    return [
        {
            "error_type": "grammar",
            "error_text": "that are determined",
            "correction": "which are determined",
            "context": "relative clause",
        },
    ]


def _article() -> ContentItem:
    return ContentItem(
        id=1,
        user_id=1,
        source_type=SourceType.CHANNEL,
        source_ref="eval",
        external_id="test",
        content_type=ContentType.ARTICLE,
        title="Ocean Currents",
        body_text=(
            "Ocean currents play a crucial role in regulating "
            "Earth's climate by distributing heat energy."
        ),
        fetched_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Generator tests
# ---------------------------------------------------------------------------


def _podcast() -> ContentItem:
    return ContentItem(
        id=2,
        user_id=1,
        source_type=SourceType.RSS,
        source_ref="eval",
        external_id="pod-test",
        content_type=ContentType.PODCAST,
        title="AI Ethics Podcast",
        body_text="Welcome to today's episode about AI ethics. " * 20,
        fetched_at=datetime.now(UTC),
    )


def _long_article() -> ContentItem:
    """An article whose body_text exceeds _PASS_THROUGH_LIMIT."""
    return ContentItem(
        id=3,
        user_id=1,
        source_type=SourceType.CHANNEL,
        source_ref="eval",
        external_id="long-test",
        content_type=ContentType.ARTICLE,
        title="Long Article",
        body_text="The ocean regulates Earth's climate. " * 200,  # ~7400 chars
        fetched_at=datetime.now(UTC),
    )


async def test_generate_worksheet_with_stub():
    """Stub LLM should produce a valid worksheet payload."""
    payload = await generate_worksheet(StubLLMClient(), _vocab(), _errors(), [_article()])
    assert isinstance(payload, WorksheetPayload)
    # Stub returns default/empty — that's OK for structure testing.
    assert payload.fill_blanks is not None


async def test_generate_worksheet_with_empty_data():
    """Generator should handle empty inputs gracefully."""
    payload = await generate_worksheet(StubLLMClient(), [], [], [])
    assert isinstance(payload, WorksheetPayload)


async def test_generate_worksheet_with_podcast():
    """Worksheet generation with podcast input should not raise."""
    payload = await generate_worksheet(
        StubLLMClient(), _vocab(), _errors(), [_article()], podcasts=[_podcast()]
    )
    assert isinstance(payload, WorksheetPayload)


async def test_prepare_text_short_passthrough():
    """Short texts (< threshold) are returned verbatim without LLM call."""
    item = _article()
    assert len(item.body_text) < _PASS_THROUGH_LIMIT
    result = await _prepare_text(StubLLMClient(), item)
    assert result == item.body_text.strip()


async def test_prepare_text_long_chunks():
    """Long texts trigger chunked extraction and return extracted content."""
    item = _long_article()
    assert len(item.body_text) > _PASS_THROUGH_LIMIT
    result = await _prepare_text(StubLLMClient(), item, max_chunks=2)
    assert "Key content extracted from" in result
    assert item.title in result


async def test_prepare_text_empty_body():
    """Empty body_text returns empty string without calling LLM."""
    item = _article()
    item = item.model_copy(update={"body_text": "   "})
    result = await _prepare_text(StubLLMClient(), item)
    assert result == ""


async def test_extract_chunks_parallel():
    """_extract_chunks should process multiple chunks and combine them."""
    long_text = "fact about oceans. " * 300  # ~6000 chars → 2 chunks of 3000
    result = await _extract_chunks(StubLLMClient(), long_text, title="Test", max_chunks=3)
    assert "Key content extracted from 'Test'" in result
    # Should have processed at least 2 chunks and joined results.
    assert result.count("[stub-llm reply]") >= 2


async def test_generate_worksheet_long_article():
    """Worksheet generation with a long article should trigger chunking and still succeed."""
    payload = await generate_worksheet(StubLLMClient(), [], [], [_long_article()])
    assert isinstance(payload, WorksheetPayload)


def test_worksheet_json_roundtrip():
    """Payload should survive JSON serialization and deserialization."""
    original = WorksheetPayload()
    json_str = worksheet_to_json(original)
    restored = worksheet_from_json(json_str)
    assert restored.fill_blanks == original.fill_blanks
    assert restored.error_correction == original.error_correction


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------


def test_render_md_includes_all_sections():
    """MD output should include headers for all exercise types."""
    from tutor.worksheet.generator import (
        CollocationMatch,
        ErrorCorrection,
        FillBlank,
        MiniReading,
        MiniReadingQuestion,
        SentenceTransform,
    )

    payload = WorksheetPayload(
        fill_blanks=[
            FillBlank(
                sentence="The ocean ________ heat energy.",
                options=["distributes", "collects", "destroys", "ignores"],
                correct_index=0,
                source_word="distributes",
            )
        ],
        error_correction=[
            ErrorCorrection(
                sentence="The circulation is driven by differences, that are determined.",
                error_span="that",
                correction="which",
                rule="Non-restrictive clause",
            )
        ],
        sentence_transform=[
            SentenceTransform(
                original="The revolution was neither sudden nor beneficial.",
                model_answer="The revolution happened gradually and had mixed effects.",
                key_point="Paraphrase 'neither...nor'",
            )
        ],
        mini_reading=[
            MiniReading(
                passage_excerpt="Ocean currents play a crucial role...",
                questions=[
                    MiniReadingQuestion(
                        prompt="What is the main idea?",
                        options=["A", "B", "C", "D"],
                        correct_index=0,
                        explanation="",
                    )
                ],
            )
        ],
        collocation_match=[
            CollocationMatch(
                word="conduct",
                correct_partner="research",
                distractors=["study", "experiment", "analysis"],
            )
        ],
    )

    md = render_worksheet_md(payload, date="2026-06-22")

    assert "Evening Worksheet — 2026-06-22" in md
    assert "Fill in the Blanks" in md
    assert "Error Correction" in md
    assert "Sentence Transformation" in md
    assert "Mini Reading" in md
    assert "Collocation Match" in md
    assert "Your answer:" in md
    assert "conduct" in md


def test_render_md_empty_payload():
    """Empty payload should still produce valid MD with header."""
    md = render_worksheet_md(WorksheetPayload())
    assert "Evening Worksheet" in md
    assert "Instructions" in md


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parse_fill_blanks():
    text = (
        "1. The ocean ________ heat.\n"
        "   A) distributes  B) collects\n"
        "   **Your answer:** A\n\n"
        "2. The word means ________.\n"
        "   **Your answer:** B\n"
    )
    answers = parse_fill_blanks(text)
    assert answers == ["A", "B"]


def test_parse_error_corrections():
    text = (
        '1. ❌ "The circulation is driven by differences, that are determined."\n'
        "   **Correct:** which are determined\n"
        "   **Rule:** Non-restrictive clause requires 'which'\n"
    )
    answers = parse_error_corrections(text)
    assert len(answers) == 1
    assert answers[0]["correct"] == "which are determined"
    assert "which" in answers[0]["rule"]


def test_parse_sentence_transforms():
    text = (
        '1. Original: "The revolution was sudden."\n'
        "   Your version: The revolution happened gradually.\n"
    )
    answers = parse_sentence_transforms(text)
    assert len(answers) == 1
    assert "gradually" in answers[0]


def test_parse_collocation_matches():
    text = "| Word | Partner |\n| conduct | A) research |\n| pose | B) a threat |\n"
    answers = parse_collocation_matches(text)
    assert len(answers) >= 1


def test_parse_worksheet_answers():
    text = (
        "**Your answer:** A\n**Correct:** which\nYour version: The revolution happened gradually.\n"
    )
    result = parse_worksheet_answers(text)
    assert "fill_blanks" in result
    assert "error_correction" in result
    assert "sentence_transform" in result
    assert "collocation_match" in result


def test_normalize_letter():
    assert normalize_letter("A") == 0
    assert normalize_letter("b") == 1
    assert normalize_letter("C") == 2
    assert normalize_letter("D") == 3
    assert normalize_letter("0") == 0
    assert normalize_letter("E") is None
    assert normalize_letter("") is None


# ---------------------------------------------------------------------------
# Repository integration tests
# ---------------------------------------------------------------------------


def test_worksheet_repo_roundtrip(repo):
    """save_worksheet → get_worksheet → update_answers → update_grade."""
    items_json = (
        '{"fill_blanks": [], "error_correction": [], '
        '"sentence_transform": [], "mini_reading": [], '
        '"collocation_match": []}'
    )
    ws_id = repo.save_worksheet(764315256, items_json)
    assert ws_id > 0

    ws = repo.get_worksheet(ws_id)
    assert ws is not None
    assert ws["status"] == "pending"
    assert ws["items_json"] == items_json

    # Submit answers.
    repo.update_worksheet_answers(ws_id, "**Your answer:** A")
    ws = repo.get_worksheet(ws_id)
    assert ws["status"] == "submitted"
    assert ws["answers"] == "**Your answer:** A"

    # Grade.
    repo.update_worksheet_grade(ws_id, 0.85, "Good work!")
    ws = repo.get_worksheet(ws_id)
    assert ws["status"] == "graded"
    assert ws["score"] == 0.85
    assert ws["feedback"] == "Good work!"


def test_get_latest_worksheet(repo):
    """Should return the most recent worksheet with given status."""
    items_json = "{}"
    repo.save_worksheet(764315256, items_json)
    repo.save_worksheet(764315256, items_json)

    ws = repo.get_latest_worksheet(764315256, status="pending")
    assert ws is not None

    # No graded worksheets yet.
    ws = repo.get_latest_worksheet(764315256, status="graded")
    assert ws is None


def test_get_vocab_today(repo, sample_raw):
    """Should return vocab from items delivered today."""
    cid = repo.add_content(sample_raw(), user_id=764315256)
    repo.mark_delivered(cid)
    repo.save_vocab(
        cid,
        [
            VocabItem(content_id=cid, word="test", definition="def", freq_rank=3.0),
        ],
    )
    vocab = repo.get_vocab_today(764315256)
    assert len(vocab) >= 1
    assert any(v.word == "test" for v in vocab)


def test_get_today_articles(repo, sample_raw):
    """Should return articles delivered today."""
    cid = repo.add_content(sample_raw(), user_id=764315256)
    repo.mark_delivered(cid)
    articles = repo.get_today_articles(764315256)
    assert len(articles) >= 1
