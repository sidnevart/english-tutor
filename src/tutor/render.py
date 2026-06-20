"""Message rendering shared by the pipeline and the bot."""

from __future__ import annotations

from tutor.domain.models import ContentItem

_PREVIEW_CHARS = 600


def render_card(item: ContentItem) -> str:
    title = item.title or "Today's reading"
    body = item.body_text.strip()
    preview = body[:_PREVIEW_CHARS] + ("…" if len(body) > _PREVIEW_CHARS else "")
    lines = [f"📰 <b>{title}</b>"]
    if item.url:
        lines.append(item.url)
    if preview:
        lines += ["", preview]
    return "\n".join(lines)


def render_score(correct: int, total: int) -> str:
    pct = round(100 * correct / total) if total else 0
    mark = "🎉" if pct >= 80 else ("👍" if pct >= 50 else "📚")
    return f"{mark} You scored <b>{correct}/{total}</b> ({pct}%)."
