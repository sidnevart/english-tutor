"""Render worksheet to Markdown and PDF formats.

The Markdown format includes answer fields the learner fills in.
PDF is generated from the Markdown via weasyprint (HTML intermediate).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tutor.domain.enums import ContentType
from tutor.domain.models import ContentItem, Quiz
from tutor.worksheet.generator import WorksheetPayload

_LETTERS = "ABCD"


def render_worksheet_md(payload: WorksheetPayload, date: str = "") -> str:
    """Render the worksheet as a Markdown string with answer fields."""
    if not date:
        date = datetime.now(UTC).strftime("%Y-%m-%d")

    parts: list[str] = [
        f"# 📝 Evening Worksheet — {date}\n",
        "## Instructions",
        "Fill in your answers below each question. When done, send this file back to the bot.\n",
        "---\n",
    ]

    # Part 1: Fill in the Blanks
    if payload.fill_blanks:
        parts.append(f"## Part 1: Fill in the Blanks ({len(payload.fill_blanks)} questions)\n")
        for i, q in enumerate(payload.fill_blanks, 1):
            parts.append(f"**{i}.** {q.sentence}\n")
            opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
            parts.append(f"   {opts}\n")
            parts.append("   **Your answer:** ____\n")

    # Part 2: Error Correction
    if payload.error_correction:
        parts.append(f"\n## Part 2: Error Correction ({len(payload.error_correction)} questions)\n")
        parts.append("*Find and correct the error in each sentence.*\n")
        for i, q in enumerate(payload.error_correction, 1):
            parts.append(f'**{i}.** ❌ "{q.sentence}"\n')
            parts.append("   **Correct:** _________________________________\n")
            parts.append("   **Rule:** _________________________________\n")

    # Part 3: Sentence Transformation
    if payload.sentence_transform:
        parts.append(
            f"\n## Part 3: Sentence Transformation ({len(payload.sentence_transform)} questions)\n"
        )
        parts.append("*Rewrite the sentence without changing its meaning.*\n")
        for i, q in enumerate(payload.sentence_transform, 1):
            parts.append(f'**{i}.** Original: "{q.original}"\n')
            parts.append("   Your version: _________________________________\n")

    # Part 4: Mini Reading Comprehension
    if payload.mini_reading:
        parts.append("\n## Part 4: Mini Reading Comprehension\n")
        parts.append("*Read the passage and answer the questions.*\n")
        for section in payload.mini_reading:
            parts.append(f"> {section.passage_excerpt}\n")
            parts.append("")
            for i, q in enumerate(section.questions, 1):
                parts.append(f"**{i}.** {q.prompt}\n")
                opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
                parts.append(f"   {opts}\n")
                parts.append("   **Your answer:** ____\n")

    # Part 5: Collocation Match
    if payload.collocation_match:
        parts.append(f"\n## Part 5: Collocation Match ({len(payload.collocation_match)} items)\n")
        parts.append("*Match each word with its natural partner.*\n")
        parts.append("| Word | Partner (write letter) |")
        parts.append("|------|----------------------|")
        for col in payload.collocation_match:
            all_opts = [col.correct_partner] + list(col.distractors)
            # Shuffle would be ideal, but we keep deterministic for testing.
            opts_str = "  ".join(f"{_LETTERS[j]}) {o}" for j, o in enumerate(all_opts))
            parts.append(f"| {col.word} | {opts_str} |")
        parts.append("")

    # Part 6: Reading Comprehension
    if payload.reading_quiz:
        n_reading = len(payload.reading_quiz)
        parts.append(f"\n## Part 6: Reading Comprehension ({n_reading} questions)\n")
        parts.append("*Read each question carefully and choose the best answer.*\n")
        # Group by source title.
        current_title = ""
        for i, q in enumerate(payload.reading_quiz, 1):
            if q.source_title and q.source_title != current_title:
                current_title = q.source_title
                parts.append(f"### 📰 {current_title}\n")
            parts.append(f"**{i}.** {q.prompt}\n")
            opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
            parts.append(f"   {opts}\n")
            parts.append("   **Your answer:** ____\n")

    # Part 7: Listening Comprehension
    if payload.listening_quiz:
        n_listening = len(payload.listening_quiz)
        parts.append(f"\n## Part 7: Listening Comprehension ({n_listening} questions)\n")
        parts.append("*Answer questions about the podcast episodes you listened to.*\n")
        current_title = ""
        for i, q in enumerate(payload.listening_quiz, 1):
            if q.source_title and q.source_title != current_title:
                current_title = q.source_title
                parts.append(f"### 🎧 {current_title}\n")
            parts.append(f"**{i}.** {q.prompt}\n")
            opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
            parts.append(f"   {opts}\n")
            parts.append("   **Your answer:** ____\n")

    # Summary
    parts.append("\n---\n")
    parts.append("## Summary\n")
    parts.append("- Total time: ____ minutes")
    parts.append("- Difficulty (1-5): ____")
    parts.append("- Notes: _________________________________\n")

    return "\n".join(parts)


def render_task_md(item: ContentItem, quiz: Quiz) -> str:
    """Render a per-item TOEFL task file the learner fills in and sends back.

    Embeds ``<!-- TASK_ID: {id} -->`` so the grader can link submissions to
    the correct quiz without the user having to do anything.
    """
    is_podcast = item.content_type == ContentType.PODCAST
    kind = "Listening" if is_podcast else "Reading"
    emoji = "🎧" if is_podcast else "📰"

    parts: list[str] = [
        f"# {emoji} TOEFL {kind} Task",
        f"<!-- TASK_ID: {item.id} -->",
        "",
        f"**{item.title or 'Untitled'}**",
        "",
        "## Instructions",
        "",
    ]
    if is_podcast:
        parts.append("Listen to the episode, then answer the questions below.")
    else:
        parts.append("Read the article, then answer the questions below.")
    parts += [
        "Fill in each **Your answer:** line with the correct letter (A, B, C, or D).",
        "When you are done, send this file back to the bot for grading.",
        "",
        "---",
        "",
        f"## Questions ({len(quiz.questions)} total)",
        "",
    ]

    for i, q in enumerate(quiz.questions, 1):
        parts.append(f"**{i}.** {q.prompt}")
        opts = "  ".join(f"{_LETTERS[j]}) {opt}" for j, opt in enumerate(q.options))
        parts.append(f"   {opts}")
        parts.append("   **Your answer:** ____")
        parts.append("")

    parts += [
        "---",
        "",
        "*Fill in your answers above and send this file back to your TOEFL coach bot.*",
    ]
    return "\n".join(parts)


def render_worksheet_pdf(md_content: str, output_path: Path | None = None) -> Path:
    """Render Markdown content to PDF via weasyprint.

    Returns the path to the generated PDF file.
    """
    try:
        import markdown as md_lib
        from weasyprint import HTML
    except ImportError:
        # Fallback: write MD only, skip PDF.
        if output_path is None:
            output_path = Path("/tmp/worksheet.pdf")
        output_path.write_text(
            "PDF generation requires 'weasyprint' and 'markdown' packages.\n"
            "Install with: pip install weasyprint markdown\n\n"
            "Here is the Markdown version instead:\n\n" + md_content,
            encoding="utf-8",
        )
        return output_path

    # Convert MD to HTML.
    html_body = md_lib.markdown(md_content, extensions=["tables", "fenced_code"])

    html_full = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: 'Georgia', serif;
    font-size: 12pt;
    line-height: 1.6;
    margin: 2cm;
    color: #333;
  }}
  h1 {{ font-size: 18pt; border-bottom: 2px solid #333; padding-bottom: 4px; }}
  h2 {{ font-size: 14pt; margin-top: 1.5em; color: #1a5276; }}
  blockquote {{
    border-left: 3px solid #aaa;
    padding-left: 1em;
    color: #555;
    font-style: italic;
    margin: 1em 0;
  }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #f0f0f0; }}
  hr {{ border: none; border-top: 1px solid #ccc; margin: 1.5em 0; }}
  strong {{ color: #2c3e50; }}
  @page {{ size: A4; margin: 2cm; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""

    if output_path is None:
        output_path = Path("/tmp/worksheet.pdf")

    HTML(string=html_full).write_pdf(str(output_path))
    return output_path
