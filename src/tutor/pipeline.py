"""The learning loop: deliver -> build evaluation -> grade & export.

Pure orchestration over Services. Works identically on stub or real adapters,
which is what makes the whole loop runnable offline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tutor.domain.enums import ContentType, DeliveryStatus, QuizKind
from tutor.domain.models import AnkiResult, ContentItem, Quiz
from tutor.eval.anki_cards import build_cards
from tutor.eval.flashcards import make_flashcards
from tutor.eval.grader import is_correct
from tutor.eval.quiz_builder import build_listening_quiz, build_reading_quiz
from tutor.eval.transcript import clean_transcript
from tutor.eval.vocab import select_vocab
from tutor.factory import Services
from tutor.memory import Memory
from tutor.render import render_card, render_score

# Simple keyword-based topic inference (no LLM call needed).
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "science": [
        "science",
        "research",
        "study",
        "experiment",
        "biology",
        "physics",
        "chemistry",
        "climate",
        "environment",
        "ecology",
        "evolution",
        "genetics",
        "neuroscience",
    ],
    "technology": [
        "technology",
        "ai",
        "artificial intelligence",
        "software",
        "computer",
        "digital",
        "internet",
        "robot",
        "automation",
        "data",
        "algorithm",
    ],
    "economics": [
        "economy",
        "economic",
        "market",
        "trade",
        "finance",
        "inflation",
        "gdp",
        "recession",
        "investment",
        "stock",
        "banking",
        "fiscal",
    ],
    "politics": [
        "politics",
        "political",
        "government",
        "election",
        "democracy",
        "policy",
        "congress",
        "parliament",
        "legislation",
        "vote",
        "president",
        "minister",
    ],
    "health": [
        "health",
        "medical",
        "disease",
        "vaccine",
        "hospital",
        "doctor",
        "patient",
        "therapy",
        "mental health",
        "nutrition",
        "exercise",
        "pandemic",
        "virus",
    ],
    "culture": [
        "culture",
        "art",
        "music",
        "film",
        "literature",
        "museum",
        "theater",
        "tradition",
        "festival",
        "heritage",
        "language",
        "religion",
    ],
    "education": [
        "education",
        "school",
        "university",
        "student",
        "teacher",
        "learning",
        "curriculum",
        "academic",
        "scholarship",
        "literacy",
        "pedagogy",
    ],
    "environment": [
        "environment",
        "climate",
        "pollution",
        "sustainability",
        "renewable",
        "carbon",
        "emissions",
        "conservation",
        "biodiversity",
        "deforestation",
    ],
    "society": [
        "society",
        "social",
        "community",
        "inequality",
        "poverty",
        "immigration",
        "urban",
        "rural",
        "demographics",
        "civil rights",
        "gender",
    ],
}


def _infer_topic(title: str, body_text: str) -> str | None:
    """Infer topic from title and body using keyword matching. Returns None if ambiguous."""
    text = (title + " " + body_text[:500]).lower()
    scores: dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[topic] = score
    if not scores:
        return None
    return max(scores, key=scores.get)  # type: ignore[arg-type]


@dataclass
class ReviewResult:
    content_id: int
    correct: int
    total: int
    anki: AnkiResult


async def _resolve_audio(url: str, dest: Path) -> Path:
    """Return a local path for the audio: a local file as-is, else download it."""
    local = Path(url.replace("file://", ""))
    if local.exists():
        return local
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


async def _clip_audio(src: Path, start_sec: int, duration_sec: int) -> Path:
    """Extract a time window from an audio file using ffmpeg. Returns the clip path."""
    import asyncio
    import shutil

    out = src.with_name(f"{src.stem}.seg{start_sec}.mp3")
    if not shutil.which("ffmpeg"):
        return src
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        str(src),
        "-t",
        str(duration_sec),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(out),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return out if proc.returncode == 0 and out.exists() else src


async def ensure_transcript(svc: Services, content_id: int) -> str:
    """Lazily transcribe a podcast: download audio + run STT, fill body_text.
    No-op for items that already have text or no audio."""
    import re

    content = svc.repo.get(content_id)
    if content is None:
        raise KeyError(f"content_item {content_id} not found")
    if content.body_text.strip() or not content.audio_url:
        return content.body_text
    audio = await _resolve_audio(content.audio_url, svc.settings.data_path / f"audio_{content_id}")

    # Detect segment window encoded as ``::seg:{i}:{start}:{end}`` in external_id.
    seg = re.search(r"::seg:\d+:(\d+):(\d+)$", content.external_id or "")
    if seg:
        start_sec = int(seg.group(1))
        end_sec = int(seg.group(2))
        audio = await _clip_audio(audio, start_sec, end_sec - start_sec)

    text = await svc.transcriber.transcribe(audio, lang=content.lang)
    text = await clean_transcript(svc.llm, text)  # strip ads / intros via LLM
    svc.repo.set_body_text(content_id, text)
    # Clean up audio we downloaded (leave caller-provided local files alone).
    if audio.name.startswith(f"audio_{content_id}") and audio.exists():
        audio.unlink(missing_ok=True)
    return text


async def send_flashcards(svc: Services, user_id: int, content_id: int) -> int:
    """Generate words+idioms Anki cards for an item and send the deck. Resilient:
    a failure (LLM/STT/network) is logged and never blocks delivery. Returns the
    number of cards sent."""
    try:
        content = svc.repo.get(content_id)
        if content is None:
            return 0
        if content.content_type == ContentType.PODCAST and not content.body_text.strip():
            await ensure_transcript(svc, content_id)
            content = svc.repo.get(content_id)
        text = (content.body_text or "").strip() if content else ""
        if not text:
            return 0
        # flashcards_per_item == 0 means unlimited (exhaustive extraction).
        limit = svc.settings.flashcards_per_item or None
        cards = await make_flashcards(svc.llm, text, limit=limit)
        if not cards:
            return 0
        result = await svc.anki.add_cards(svc.settings.anki_deck, cards)
        svc.repo.save_anki_cards(content_id, cards, svc.settings.anki_deck, result.sink)
        if result.apkg_path:
            kind = "episode" if content.content_type == ContentType.PODCAST else "article"
            await svc.notifier.send_file(
                user_id,
                Path(result.apkg_path),
                caption=f"🎴 {len(cards)} words & idioms from this {kind}",
            )
        return len(cards)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("flashcards", "error", str(exc)[:200])
        return 0


async def send_more_flashcards(svc: Services, user_id: int, content_id: int | None = None) -> int:
    """Generate ADDITIONAL Anki cards for an item, skipping terms already carded.

    Defaults to the learner's most recently delivered item. Returns cards sent.
    """
    try:
        content = (
            svc.repo.get(content_id)
            if content_id is not None
            else svc.repo.latest_delivered_content(user_id)
        )
        if content is None:
            await svc.notifier.send(user_id, "No material yet — use /next first.")
            return 0
        if content.content_type == ContentType.PODCAST and not content.body_text.strip():
            await ensure_transcript(svc, content.id)
            content = svc.repo.get(content.id)
        text = (content.body_text or "").strip() if content else ""
        if not text:
            return 0
        exclude = svc.repo.anki_fronts_for_content(content.id)
        cards = await make_flashcards(svc.llm, text, limit=None, exclude=exclude)
        if not cards:
            await svc.notifier.send(user_id, "No new cards to add — looks exhaustive already. 🎉")
            return 0
        result = await svc.anki.add_cards(svc.settings.anki_deck, cards)
        svc.repo.save_anki_cards(content.id, cards, svc.settings.anki_deck, result.sink)
        if result.apkg_path:
            await svc.notifier.send_file(
                user_id,
                Path(result.apkg_path),
                caption=f"🎴 {len(cards)} more cards from “{content.title or 'this item'}”",
            )
        return len(cards)
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("flashcards_more", "error", str(exc)[:200])
        return 0


async def send_task_file(svc: Services, user_id: int, item: ContentItem) -> bool:
    """Generate a TOEFL quiz for one item, save to DB, render to .md, send file.

    Resilient: failures are logged and never block the delivery flow.
    Returns True if the file was sent.
    """
    import tempfile

    from tutor.worksheet.renderer import render_task_md

    try:
        quiz = await build_evaluation(svc, item.id, user_id)
        md = render_task_md(item, quiz)
        kind = "listening" if item.content_type == ContentType.PODCAST else "reading"
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md",
            prefix=f"task_{kind}_{item.id}_",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(md)
            tmp = Path(f.name)
        caption = f"📝 Your TOEFL {kind} task — fill in and send back"
        await svc.notifier.send_file(user_id, tmp, caption=caption)
        tmp.unlink(missing_ok=True)
        return True
    except Exception as exc:  # noqa: BLE001
        svc.repo.log_job("task_file", "error", str(exc)[:200])
        return False


async def deliver_new(
    svc: Services, user_id: int, limit: int = 5, content_type: ContentType | None = None
) -> list[int]:
    """Push NEW items (optionally of one type) to the learner, mark DELIVERED,
    send the words+idioms Anki deck, and immediately attach a TOEFL task file."""
    max_len = svc.settings.max_article_len
    delivered: list[int] = []
    for item in svc.repo.fetch_by_status(user_id, DeliveryStatus.NEW, limit, content_type):
        if item.content_type == ContentType.ARTICLE and len(item.body_text) > max_len:
            svc.repo.set_body_text(item.id, item.body_text[:max_len] + "…")
            item = svc.repo.get(item.id) or item
        await svc.notifier.send(user_id, render_card(item))
        svc.repo.mark_delivered(item.id)
        await send_flashcards(svc, user_id, item.id)
        await send_task_file(svc, user_id, item)
        delivered.append(item.id)
    return delivered


async def build_evaluation(
    svc: Services,
    content_id: int,
    user_id: int,
    *,
    vocab_limit: int = 8,
    n_questions: int | None = None,
) -> Quiz:
    """Select vocabulary (deterministic) and generate a reading quiz (LLM),
    using the learner's persona + recall memory to shape the questions.

    `n_questions` defaults to the configured TOEFL set size (reading vs listening).
    """
    content = svc.repo.get(content_id)
    if content is None:
        raise KeyError(f"content_item {content_id} not found")

    # Podcasts arrive without text; transcribe lazily before evaluating.
    if not content.body_text.strip() and content.audio_url:
        await ensure_transcript(svc, content_id)
        content = svc.repo.get(content_id)
        assert content is not None

    svc.repo.save_vocab(content_id, select_vocab(content_id, content.body_text, limit=vocab_limit))

    mem = Memory(svc.settings.soul_dir, user_id)
    if content.content_type == ContentType.PODCAST:
        n = n_questions if n_questions is not None else svc.settings.listening_questions
        questions = await build_listening_quiz(
            svc.llm, content, n=n, system=mem.persona(), recall_hint=mem.recall_hint()
        )
        svc.repo.save_quiz(content_id, QuizKind.LISTENING, questions)
    else:
        n = n_questions if n_questions is not None else svc.settings.reading_questions
        questions = await build_reading_quiz(
            svc.llm, content, n=n, system=mem.persona(), recall_hint=mem.recall_hint()
        )
        svc.repo.save_quiz(content_id, QuizKind.READING, questions)

    quiz = svc.repo.get_quiz_auto(content_id)
    assert quiz is not None
    return quiz


async def finalize_review(svc: Services, content_id: int, user_id: int) -> ReviewResult:
    """Grade from recorded attempts, export Anki cards, mark REVIEWED.

    Derives the missed questions from the `attempt` table (the source of truth),
    so it works whether answers were recorded one-by-one (interactive bot) or in
    a batch. Idempotent: if already REVIEWED it does not re-transition.
    """
    quiz = svc.repo.get_quiz_auto(content_id)
    if quiz is None:
        raise KeyError(f"no quiz for content_item {content_id}")

    attempts = {a.quiz_question_id: a for a in svc.repo.attempts_for_content(content_id, user_id)}
    missed = [q for q in quiz.questions if not (attempts.get(q.id) and attempts[q.id].is_correct)]
    correct = len(quiz.questions) - len(missed)

    content = svc.repo.get(content_id)
    assert content is not None
    vocab = svc.repo.get_vocab(content_id)
    cards = build_cards(content, vocab, missed)
    anki = await svc.anki.add_cards(svc.settings.anki_deck, cards)
    svc.repo.save_anki_cards(content_id, cards, svc.settings.anki_deck, anki.sink)

    if content.status != DeliveryStatus.REVIEWED:
        svc.repo.mark_reviewed(content_id)

    # Accumulate today's vocabulary into the learner's recall memory.
    Memory(svc.settings.soul_dir, user_id).add_weak_words([v.word for v in vocab])

    # Track topic progress from quiz score.
    topic = _infer_topic(content.title, content.body_text)
    if topic:
        score = correct / len(quiz.questions) if quiz.questions else 0
        svc.repo.record_topic_progress(user_id, topic, "quiz", content_id, score)

    return ReviewResult(content_id, correct, len(quiz.questions), anki)


async def submit_answers(
    svc: Services, content_id: int, user_id: int, answers: dict[int, int]
) -> ReviewResult:
    """Record a batch of answers, then finalize. (The bot records incrementally
    and calls finalize_review directly.)"""
    quiz = svc.repo.get_quiz_auto(content_id)
    if quiz is None:
        raise KeyError(f"no quiz for content_item {content_id}")

    for q in quiz.questions:
        chosen = answers.get(q.id, -1)
        svc.repo.record_attempt(q.id, user_id, chosen, is_correct(q, chosen))

    result = await finalize_review(svc, content_id, user_id)
    await svc.notifier.send(user_id, render_score(result.correct, result.total))
    if result.anki.apkg_path:
        await svc.notifier.send_file(
            user_id, Path(result.anki.apkg_path), caption="🎴 Your Anki cards for today"
        )
    return result
