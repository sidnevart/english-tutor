"""The single daily TOEFL file: Reading passages + Listening (audio) + Vocabulary.

One self-contained Markdown file delivered each morning. The learner reads the
embedded passages, listens to the attached podcast audio, fills in their answers,
and sends the file back. Grading reuses the existing per-content pipeline
(`build_evaluation` generates + saves the quiz and vocab; `finalize_review`
records attempts, builds Anki cards, marks REVIEWED, tracks topic progress).

This replaces the old per-item task files and the evening homework/worksheet.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from tutor.domain.enums import ContentType, QuizKind
from tutor.domain.models import ContentItem, QuizQuestion
from tutor.eval.grader import is_correct
from tutor.eval.quiz_builder import build_listening_quiz, build_reading_quiz
from tutor.factory import Services
from tutor.memory import Memory
from tutor.pipeline import _clip_audio, _resolve_audio, ensure_transcript, finalize_review
from tutor.worksheet.generator import CollocationMatch, FillBlank, VocabExercisesPayload
from tutor.worksheet.parser import normalize_letter

_LETTERS = "ABCDEFGH"


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


class DailyReadingBlock(BaseModel):
    content_id: int
    title: str
    passage: str
    questions: list[QuizQuestion] = Field(default_factory=list)


class DailyListeningBlock(BaseModel):
    content_id: int
    title: str
    questions: list[QuizQuestion] = Field(default_factory=list)


class DailyPayload(BaseModel):
    date: str
    reading: list[DailyReadingBlock] = Field(default_factory=list)
    listening: list[DailyListeningBlock] = Field(default_factory=list)
    fill_blanks: list[FillBlank] = Field(default_factory=list)
    collocation_match: list[CollocationMatch] = Field(default_factory=list)

    @property
    def total_questions(self) -> int:
        return (
            sum(len(b.questions) for b in self.reading)
            + sum(len(b.questions) for b in self.listening)
            + len(self.fill_blanks)
            + len(self.collocation_match)
        )


# ---------------------------------------------------------------------------
# Vocab exercises (fill_blanks + collocation) — one focused LLM call
# ---------------------------------------------------------------------------

_VOCAB_SYSTEM = (
    "You are a TOEFL vocabulary exercise writer. Using ONLY the vocabulary words "
    "provided (and the article context if given), write two short exercise sets:\n\n"
    "1. fill_blanks (5 items): a sentence with a ________ blank and 4 options where "
    "exactly one fits grammatically and semantically. Set correct_index (0-3) and "
    "source_word (the tested word).\n"
    "2. collocation_match (5 items): a word + its correct natural partner + 3 "
    "plausible distractors.\n\n"
    "All text in English, B2-C1 difficulty. Return JSON matching the schema."
)


async def generate_vocab_exercises(
    llm: object, vocab: list, articles: list[ContentItem]
) -> tuple[list[FillBlank], list[CollocationMatch]]:
    """Generate fill_blanks + collocation exercises from today's vocab."""
    if not vocab and not articles:
        return [], []
    vocab_lines = [f"  - {v.word}: {v.definition}" for v in vocab[:15]] or ["  (none)"]
    article_ctx = "\n".join(a.body_text[:800] for a in articles[:2]) or "(no articles)"
    user = "VOCABULARY:\n" + "\n".join(vocab_lines) + f"\n\nARTICLE CONTEXT:\n{article_ctx}"
    payload = await llm.complete_json(_VOCAB_SYSTEM, user, VocabExercisesPayload)  # type: ignore[attr-defined]
    return payload.fill_blanks, payload.collocation_match


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


async def build_daily_payload(
    svc: Services,
    user_id: int,
    articles: list[ContentItem],
    podcasts: list[ContentItem],
) -> DailyPayload:
    """Build the daily payload: high-quality TOEFL quizzes per item + vocab exercises.

    Quizzes are saved to the DB (quiz table) and vocab to the vocab table, so the
    existing grading/Anki/topic-progress machinery in `finalize_review` works when
    the learner sends the file back.
    """
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    reading: list[DailyReadingBlock] = []
    listening: list[DailyListeningBlock] = []

    for art in articles:
        n = svc.settings.reading_questions_per_item
        questions = await build_reading_quiz(
            svc.llm, art, n=n, recall_hint=Memory(svc.settings.soul_dir, user_id).recall_hint()
        )
        svc.repo.save_quiz(art.id, QuizKind.READING, questions)
        reading.append(
            DailyReadingBlock(
                content_id=art.id, title=art.title or "Today's reading", passage=art.body_text
            )
        )
        reading[-1].questions = questions

    for pod in podcasts:
        if not pod.body_text.strip():
            try:
                await ensure_transcript(svc, pod.id)
            except Exception:  # noqa: BLE001
                pass
            pod = svc.repo.get(pod.id) or pod
        if not pod.body_text.strip():
            continue  # skip podcasts we couldn't transcribe
        n = svc.settings.listening_questions_per_item
        questions = await build_listening_quiz(
            svc.llm, pod, n=n, recall_hint=Memory(svc.settings.soul_dir, user_id).recall_hint()
        )
        svc.repo.save_quiz(pod.id, QuizKind.LISTENING, questions)
        listening.append(
            DailyListeningBlock(content_id=pod.id, title=pod.title or "Today's episode")
        )
        listening[-1].questions = questions

    # Vocab (from today's content) + fill_blanks/collocation exercises.
    vocab = _collect_today_vocab(svc, articles, podcasts)
    fill_blanks, collocation = await generate_vocab_exercises(svc.llm, vocab, articles)

    return DailyPayload(
        date=date,
        reading=reading,
        listening=listening,
        fill_blanks=fill_blanks,
        collocation_match=collocation,
    )


def _collect_today_vocab(svc: Services, articles: list[ContentItem], podcasts: list[ContentItem]):
    """Gather vocab items already saved for today's content (by build_evaluation
    is not called here, so fall back to repo.get_vocab per content)."""
    from tutor.eval.vocab import select_vocab

    out = []
    for item in articles + podcasts:
        if not item.body_text.strip():
            continue
        existing = svc.repo.get_vocab(item.id)
        if not existing:
            # Lazy vocab selection for items that don't have it yet.
            picked = select_vocab(item.id, item.body_text, limit=8)
            svc.repo.save_vocab(item.id, picked)
            existing = picked
        out.extend(existing)
    return out


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render_daily_md(payload: DailyPayload, worksheet_id: int) -> str:
    """Render the daily TOEFL file as Markdown with answer fields."""
    parts: list[str] = [
        f"# 📝 Daily TOEFL — {payload.date}",
        f"<!-- WORKSHEET_ID: {worksheet_id} -->",
        "",
        "## Instructions",
        "Read the passage(s), listen to the attached audio for the listening part, "
        "fill in each **Your answer:** line with the correct letter, then send this "
        "file back to the bot for grading.",
        "",
        "---",
        "",
    ]

    # Part 1: Reading (passage + questions)
    n_read = sum(len(b.questions) for b in payload.reading)
    parts.append(f"## Part 1: Reading ({n_read} questions)\n")
    for bi, block in enumerate(payload.reading, 1):
        parts.append(f"### 📰 {block.title}\n")
        parts.append(block.passage.strip() + "\n")
        for i, q in enumerate(block.questions, 1):
            parts.append(f"**R{bi}.{i}.** {q.prompt}")
            opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
            parts.append(f"   {opts}")
            parts.append("   **Your answer:** ____")
            parts.append("")
    parts.append("---\n")

    # Part 2: Listening (questions only — audio is sent as a separate file)
    n_listen = sum(len(b.questions) for b in payload.listening)
    parts.append(f"## Part 2: Listening ({n_listen} questions)\n")
    parts.append(
        "*Listen to the attached audio file(s), then answer. The transcript is "
        "not provided — just like the real exam.*\n"
    )
    for bi, block in enumerate(payload.listening, 1):
        parts.append(f"### 🎧 {block.title}\n")
        for i, q in enumerate(block.questions, 1):
            parts.append(f"**L{bi}.{i}.** {q.prompt}")
            opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
            parts.append(f"   {opts}")
            parts.append("   **Your answer:** ____")
            parts.append("")
    parts.append("---\n")

    # Part 3: Vocabulary
    has_vocab = bool(payload.fill_blanks or payload.collocation_match)
    if has_vocab:
        parts.append("## Part 3: Vocabulary\n")
    if payload.fill_blanks:
        parts.append("*Fill in the blank (5 items).*\n")
        for i, q in enumerate(payload.fill_blanks, 1):
            parts.append(f"**V{i}.** {q.sentence}")
            opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
            parts.append(f"   {opts}")
            parts.append("   **Your answer:** ____")
            parts.append("")
    if payload.collocation_match:
        parts.append("*Match each word with its natural partner.*\n")
        parts.append("| Word | A | B | C | D |")
        parts.append("|------|---|---|---|---|")
        for col in payload.collocation_match:
            all_opts = [col.correct_partner] + list(col.distractors)
            opts_str = " | ".join(all_opts)
            parts.append(f"| {col.word} | {opts_str} |")
            parts.append("   **Your answer (letter):** ____")
        parts.append("")
    if has_vocab:
        parts.append("---\n")

    parts.append("*Fill in your answers above and send this file back to your TOEFL coach bot.*")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parse + grade
# ---------------------------------------------------------------------------


def _section_answers(text: str, heading: str) -> list[str]:
    """All 'Your answer:' values within a ## section (in order).

    The lookahead stops at the next h2 heading (``\\n## ``) so h3 subheadings
    inside the section (``### 📰 title``) don't truncate it.
    """
    pattern = rf"## {re.escape(heading)}.*?(?=\n## |\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return []
    return [s.strip().upper() for s in re.findall(r"\*\*Your answer[^*]*:\*\*\s*(.+)", m.group())]


def parse_daily_answers(text: str, payload: DailyPayload) -> dict[str, list[str]]:
    """Parse the learner's answers from a filled-in daily file."""
    reading = _section_answers(text, "Part 1: Reading")
    listening = _section_answers(text, "Part 2: Listening")
    vocab = _section_answers(text, "Part 3: Vocabulary")
    # Vocab "Your answer:" lines = fill_blanks (collocation uses its own lines).
    fill = vocab[: len(payload.fill_blanks)]
    collocation = vocab[len(payload.fill_blanks) :]
    return {
        "reading": reading,
        "listening": listening,
        "fill_blanks": fill,
        "collocation": collocation,
    }


async def grade_daily(
    svc: Services, user_id: int, payload: DailyPayload, answers_text: str
) -> tuple[float, str]:
    """Grade a returned daily file: record attempts, finalize each content item
    (Anki + REVIEWED + topic progress), score vocab, and return (score, HTML feedback)."""
    answers = parse_daily_answers(answers_text, payload)

    # Map reading/listening answers to questions in document order.
    r_answers = answers["reading"]
    l_answers = answers["listening"]
    r_idx = 0
    l_idx = 0
    per_content: dict[int, tuple[int, int]] = {}  # content_id -> (correct, total)

    for block in payload.reading:
        correct = 0
        for q in block.questions:
            chosen = normalize_letter(r_answers[r_idx]) if r_idx < len(r_answers) else None
            chosen = chosen if chosen is not None else -1
            ok = is_correct(q, chosen)
            if q.id is not None:
                svc.repo.record_attempt(q.id, user_id, chosen, ok)
            correct += int(ok)
            r_idx += 1
        per_content[block.content_id] = (correct, len(block.questions))

    for block in payload.listening:
        correct = 0
        for q in block.questions:
            chosen = normalize_letter(l_answers[l_idx]) if l_idx < len(l_answers) else None
            chosen = chosen if chosen is not None else -1
            ok = is_correct(q, chosen)
            if q.id is not None:
                svc.repo.record_attempt(q.id, user_id, chosen, ok)
            correct += int(ok)
            l_idx += 1
        per_content[block.content_id] = (correct, len(block.questions))

    # Finalize each content item: Anki cards from missed, mark REVIEWED, topic progress.
    anki_paths: list[Path] = []
    for content_id in per_content:
        try:
            result = await finalize_review(svc, content_id, user_id)
            if result.anki.apkg_path:
                anki_paths.append(Path(result.anki.apkg_path))
        except Exception:  # noqa: BLE001
            pass

    # Vocab scoring (deterministic).
    fb_correct = sum(
        1
        for i, q in enumerate(payload.fill_blanks)
        if i < len(answers["fill_blanks"])
        and normalize_letter(answers["fill_blanks"][i]) == q.correct_index
    )
    fb_total = len(payload.fill_blanks)
    col_correct = sum(
        1
        for i in range(min(len(payload.collocation_match), len(answers["collocation"])))
        if normalize_letter(answers["collocation"][i]) == 0  # correct partner is first
    )
    col_total = len(payload.collocation_match)

    # Build feedback.
    r_correct = sum(c for c, _ in per_content.values())
    r_total = sum(t for _, t in per_content.values())
    lines = ["📊 <b>Daily TOEFL Results</b>\n"]
    if r_total:
        pct = round(100 * r_correct / r_total)
        lines.append(f"📰 Reading: <b>{r_correct}/{r_total}</b> ({pct}%)")
    if r_total and fb_total:
        fb_pct = round(100 * fb_correct / fb_total) if fb_total else 0
        lines.append(f"🔤 Vocab fill-in: <b>{fb_correct}/{fb_total}</b> ({fb_pct}%)")
    if col_total:
        col_pct = round(100 * col_correct / col_total)
        lines.append(f"🔗 Collocations: <b>{col_correct}/{col_total}</b> ({col_pct}%)")

    # Per-item breakdown.
    if per_content:
        lines.append("\n<b>By item:</b>")
        for cid, (c, t) in per_content.items():
            item = svc.repo.get(cid)
            title = (item.title or "item") if item else "item"
            kind = "🎧" if (item and item.content_type == ContentType.PODCAST) else "📰"
            lines.append(f"  {kind} {title}: {c}/{t}")

    if anki_paths:
        lines.append(f"\n🎴 Anki cards generated for missed questions: {len(anki_paths)} deck(s)")
    lines.append("\nReview your Anki cards and keep the streak! 📚")

    # Deliver the missed-cards Anki deck(s) built by finalize_review.
    for path in anki_paths:
        try:
            if path.exists():
                await svc.notifier.send_file(
                    user_id, path, caption="🎴 Anki cards for missed questions"
                )
        except Exception:  # noqa: BLE001
            pass

    total_correct = r_correct + fb_correct + col_correct
    total_q = r_total + fb_total + col_total
    overall = total_correct / total_q if total_q else 0.0
    return overall, "\n".join(lines)


# ---------------------------------------------------------------------------
# Serialization (stored in the worksheet table's items_json)
# ---------------------------------------------------------------------------


def daily_to_json(payload: DailyPayload) -> str:
    return payload.model_dump_json(indent=2)


def daily_from_json(data: str) -> DailyPayload:
    return DailyPayload.model_validate_json(data)


# ---------------------------------------------------------------------------
# Delivery (build + save + send .md and podcast audio)
# ---------------------------------------------------------------------------


async def _resolve_delivery_audio(svc: Services, content: ContentItem) -> Path | None:
    """Return a local audio path to send for a podcast, clipping to the segment
    window if the episode was split. None if no audio / download fails."""
    if not content.audio_url:
        return None
    try:
        dest = svc.settings.data_path / f"listen_{content.id}.mp3"
        audio = await _resolve_audio(content.audio_url, dest)
        seg = re.search(r"::seg:\d+:(\d+):(\d+)$", content.external_id or "")
        if seg:
            start = int(seg.group(1))
            end = int(seg.group(2))
            audio = await _clip_audio(audio, start, end - start)
        return audio
    except Exception:  # noqa: BLE001
        return None


async def send_daily_file(svc: Services, user_id: int, content_ids: list[int]) -> bool:
    """Build the single daily TOEFL file from the just-delivered content, save it
    (pending worksheet), and send the .md + each podcast's audio. Returns True if
    a file was sent."""
    items = [svc.repo.get(cid) for cid in content_ids if cid]
    items = [it for it in items if it is not None]
    articles = [it for it in items if it.content_type == ContentType.ARTICLE]
    podcasts = [it for it in items if it.content_type == ContentType.PODCAST]

    if not articles and not podcasts:
        await svc.notifier.send(
            user_id,
            "📝 No material yet to build today's TOEFL file. "
            "Use /next to get content, then /daily.",
        )
        return False

    try:
        payload = await build_daily_payload(svc, user_id, articles, podcasts)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("daily_file", "error", str(exc)[:200])
        await svc.notifier.send(user_id, "Couldn't build today's TOEFL file. Try /daily later.")
        return False

    worksheet_id = svc.repo.save_worksheet(user_id, daily_to_json(payload))
    md = render_daily_md(payload, worksheet_id)
    md_path = svc.settings.data_path / f"daily_toefl_{payload.date}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")

    n_read = sum(len(b.questions) for b in payload.reading)
    n_listen = sum(len(b.questions) for b in payload.listening)
    await svc.notifier.send(
        user_id,
        f"📝 <b>Daily TOEFL — {payload.date}</b>\n"
        f"  • Reading: {len(payload.reading)} passage(s), {n_read} questions\n"
        f"  • Listening: {len(payload.listening)} audio piece(s), {n_listen} questions\n"
        f"  • Vocabulary: {len(payload.fill_blanks)} fill-in + "
        f"{len(payload.collocation_match)} collocation\n\n"
        f"Read, listen to the attached audio, fill in your answers and send this file back!",
    )
    await svc.notifier.send_file(user_id, md_path, caption=f"📝 Daily TOEFL — {payload.date}")

    # Send each podcast's audio so the listening part is doable.
    for block in payload.listening:
        content = svc.repo.get(block.content_id)
        if content is None:
            continue
        audio = await _resolve_delivery_audio(svc, content)
        if audio is not None and audio.exists():
            await svc.notifier.send_file(
                user_id, audio, caption=f"🎧 Listen: {block.title}"
            )

    svc.repo.log_job(
        "daily_file",
        "ok",
        f"worksheet_id={worksheet_id} reading={len(payload.reading)} "
        f"listening={len(payload.listening)}",
    )
    return True