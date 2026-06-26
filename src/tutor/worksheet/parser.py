"""Utility parsers for worksheet answers.

Only `normalize_letter` is still used — it converts a learner's letter answer
(A/B/C/D or 1-4) into a 0-based index.  The richer section-aware parsers that
supported the old evening worksheet were removed when the daily TOEFL file
consolidated all task delivery; those are now in `daily_file._section_answers`.
"""

from __future__ import annotations


def normalize_letter(answer: str) -> int | None:
    """Convert a letter answer (A/B/C/D) to an index (0/1/2/3).

    Returns None if the answer is not a valid letter.
    """
    answer = answer.strip().upper()
    if len(answer) == 1 and answer in "ABCD":
        return ord(answer) - ord("A")
    # Also accept numeric answers.
    if answer.isdigit() and 0 <= int(answer) <= 3:
        return int(answer)
    return None