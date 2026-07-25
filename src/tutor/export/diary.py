"""Export the learner's error diary as files.

`/diary` (no arg) sends all three formats; `/diary md|csv|apkg` sends one.
Backed by `Repository.error_diary` (frequency + first/last seen + last
correction/context per distinct error), the Anki machinery
(`Services.anki.add_cards` → `.apkg`), and `Notifier.send_file`.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from tutor.domain.models import Card
from tutor.factory import Services

_FORMATS = {"md", "csv", "apkg"}
_TOP_CARDS = 40  # cap the Anki deck to the most frequent errors


def _short(iso: str) -> str:
    """Trim an ISO timestamp to a readable date (defensive against empties)."""
    return (iso or "").replace("T", " ")[:16]


def markdown_diary(rows: list[dict]) -> str:
    """Render the diary as Markdown grouped by error type."""
    by_type: dict[str, list[dict]] = {}
    for r in rows:
        by_type.setdefault(str(r["error_type"]), []).append(r)

    total = sum(int(r["count"]) for r in rows)
    lines = ["# Error diary", "", f"_{len(rows)} distinct errors · {total} occurrences_", ""]

    for error_type in sorted(by_type):
        lines.append(f"## {error_type}")
        lines.append("")
        for r in by_type[error_type]:
            lines.append(f"### ❌ {r['error_text']}")
            lines.append(f"- **Fix:** {r['correction']}")
            lines.append(f"- **Count:** {r['count']}")
            lines.append(f"- **First seen:** {_short(str(r['first_seen']))}")
            lines.append(f"- **Last seen:** {_short(str(r['last_seen']))}")
            ctx = str(r.get("last_context") or "").strip()
            if ctx:
                lines.append(f"- **Context:** {ctx}")
            lines.append("")

    return "\n".join(lines)


_CSV_COLUMNS = ["error", "correction", "type", "count", "first_seen", "last_seen", "last_context"]


def write_csv_diary(rows: list[dict], path: Path) -> None:
    """Write a sortable CSV (one row per distinct error)."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_CSV_COLUMNS)
        for r in rows:
            writer.writerow(
                [
                    r["error_text"],
                    r["correction"],
                    r["error_type"],
                    r["count"],
                    r["first_seen"],
                    r["last_seen"],
                    r.get("last_context") or "",
                ]
            )


def error_card(row: dict) -> Card:
    """Build an Anki card: front = error + context, back = correction."""
    front = f"{row['error_text']}"
    ctx = str(row.get("last_context") or "").strip()
    if ctx:
        front += f"\n\n{ctx}"
    return Card(
        front=front,
        back=str(row["correction"]),
        tags=["error", str(row["error_type"])],
    )


async def export_diary(svc: Services, user_id: int, fmt: str | None = None) -> None:
    """Generate and send the diary file(s). `fmt` in {None, md, csv, apkg}."""
    svc.repo.ensure_subscriber(user_id)

    if fmt is not None and fmt not in _FORMATS:
        await svc.notifier.send(
            user_id,
            f"Unknown format '{fmt}'. Use /diary (all) or /diary md|csv|apkg.",
        )
        return

    rows = svc.repo.error_diary(user_id)
    if not rows:
        await svc.notifier.send(
            user_id,
            "📭 Your error diary is empty — finish a /speak or /write session "
            "(then /stop) so I can capture some errors first.",
        )
        return

    wants = _FORMATS if fmt is None else {fmt}
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    out_dir = Path(svc.settings.data_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if "md" in wants:
        path = out_dir / f"diary_{user_id}_{stamp}.md"
        path.write_text(markdown_diary(rows), encoding="utf-8")
        await svc.notifier.send_file(user_id, path, caption="📓 Error diary (Markdown)")

    if "csv" in wants:
        path = out_dir / f"diary_{user_id}_{stamp}.csv"
        write_csv_diary(rows, path)
        await svc.notifier.send_file(user_id, path, caption="📊 Error diary (CSV)")

    if "apkg" in wants:
        cards = [error_card(r) for r in rows[:_TOP_CARDS]]
        result = await svc.anki.add_cards(svc.settings.anki_deck, cards)
        if result.apkg_path:
            await svc.notifier.send_file(
                user_id,
                Path(result.apkg_path),
                caption=f"🎴 {len(cards)} error card(s) (Anki)",
            )
