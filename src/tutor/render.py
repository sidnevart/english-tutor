"""Message rendering shared by the pipeline and the bot."""

from __future__ import annotations

from tutor.domain.enums import ContentType
from tutor.domain.models import ContentItem, QuizQuestion

_PREVIEW_CHARS = 600
_LETTERS = "ABCDEFGH"


def render_card(item: ContentItem) -> str:
    if item.content_type == ContentType.PODCAST:
        return _render_podcast(item)
    return _render_article(item)


def _render_article(item: ContentItem) -> str:
    title = item.title or "Today's reading"
    body = item.body_text.strip()
    preview = body[:_PREVIEW_CHARS] + ("…" if len(body) > _PREVIEW_CHARS else "")
    word_count = len(body.split())
    read_min = max(1, round(word_count / 200))  # ~200 wpm average
    lines = [f"📰 <b>{title}</b> · ~{read_min} min read"]
    if item.url:
        lines.append(item.url)
    if preview:
        lines += ["", preview]
    return "\n".join(lines)


def _render_podcast(item: ContentItem) -> str:
    title = item.title or "Today's episode"
    mins = f" · {item.duration_sec // 60} min" if item.duration_sec else ""
    lines = [f"🎧 <b>{title}</b>{mins}"]
    if item.source_ref:
        lines.append(f"<i>{item.source_ref}</i>")
    if item.url:
        lines.append(item.url)
    lines += ["", "Tap below for a listening quiz on this episode."]
    return "\n".join(lines)


def render_question(index: int, total: int, question: QuizQuestion) -> str:
    options = "\n".join(f"<b>{_LETTERS[i]}.</b> {opt}" for i, opt in enumerate(question.options))
    return f"<b>Question {index + 1}/{total}</b>\n\n{question.prompt}\n\n{options}"


def render_score(correct: int, total: int) -> str:
    pct = round(100 * correct / total) if total else 0
    mark = "🎉" if pct >= 80 else ("👍" if pct >= 50 else "📚")
    return f"{mark} You scored <b>{correct}/{total}</b> ({pct}%)."
