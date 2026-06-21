"""The repository: sole writer of the database and owner of the state machine.

Callers use intent verbs (`add_content`, `mark_delivered`, `record_attempt`,
`mark_reviewed`, ...) rather than raw SQL. Status changes go through
`_transition`, which enforces `LEGAL_TRANSITIONS` in Python; the SQLite trigger
is a second, independent guard.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from tutor.domain.enums import ContentType, DeliveryStatus, QuizKind, is_legal_transition
from tutor.domain.models import (
    Attempt,
    Card,
    ContentItem,
    Quiz,
    QuizQuestion,
    RawItem,
    VocabItem,
)


class InvalidTransition(Exception):
    """Raised when an illegal content_item status transition is attempted."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---- subscribers -------------------------------------------------------
    def ensure_subscriber(self, user_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO subscriber (user_id, joined_at) VALUES (?, ?)",
            (user_id, _now()),
        )
        self.conn.commit()

    # ---- content ingestion -------------------------------------------------
    def add_content(self, item: RawItem, user_id: int) -> int | None:
        """Insert a scraped/ingested item. Returns the new id, or None if it is
        a duplicate — idempotent on (source_ref, external_id) and, across
        sources, on the body hash (so the same post cross-posted to two channels
        is stored once)."""
        body = item.body_text.strip()
        body_hash = hashlib.sha1(body.encode("utf-8")).hexdigest() if body else ""
        if body_hash:
            dup = self.conn.execute(
                "SELECT 1 FROM content_item WHERE user_id = ? AND body_hash = ?",
                (user_id, body_hash),
            ).fetchone()
            if dup:
                return None

        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO content_item
                (user_id, source_type, source_ref, external_id, content_type,
                 title, url, body_text, audio_url, duration_sec, lang,
                 cadence_bucket, status, fetched_at, body_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NEW', ?, ?)
            """,
            (
                user_id,
                item.source_type.value,
                item.source_ref,
                item.external_id,
                item.content_type.value,
                item.title,
                item.url,
                item.body_text,
                item.audio_url,
                item.duration_sec,
                item.lang,
                item.cadence_bucket.value if item.cadence_bucket else None,
                _now(),
                body_hash,
            ),
        )
        self.conn.commit()
        return cur.lastrowid if cur.rowcount else None

    def get(self, content_id: int) -> ContentItem | None:
        row = self.conn.execute("SELECT * FROM content_item WHERE id = ?", (content_id,)).fetchone()
        return self._to_content(row) if row else None

    def fetch_by_status(
        self,
        user_id: int,
        status: DeliveryStatus,
        limit: int = 50,
        content_type: ContentType | None = None,
    ) -> list[ContentItem]:
        sql = "SELECT * FROM content_item WHERE user_id = ? AND status = ?"
        params: list[object] = [user_id, status.value]
        if content_type is not None:
            sql += " AND content_type = ?"
            params.append(content_type.value)
        sql += " ORDER BY fetched_at ASC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [self._to_content(r) for r in rows]

    def set_body_text(self, content_id: int, body_text: str) -> None:
        """Fill in a podcast transcript (or correct an article body)."""
        self.conn.execute(
            "UPDATE content_item SET body_text = ? WHERE id = ?", (body_text, content_id)
        )
        self.conn.commit()

    # ---- state machine -----------------------------------------------------
    def mark_delivered(self, content_id: int) -> None:
        self._transition(content_id, DeliveryStatus.DELIVERED)

    def mark_reviewed(self, content_id: int) -> None:
        self._transition(content_id, DeliveryStatus.REVIEWED)

    def mark_skipped(self, content_id: int) -> None:
        self._transition(content_id, DeliveryStatus.SKIPPED)

    def mark_failed(self, content_id: int) -> None:
        self._transition(content_id, DeliveryStatus.FAILED)

    def requeue(self, content_id: int) -> None:
        self._transition(content_id, DeliveryStatus.NEW)

    def _transition(self, content_id: int, dst: DeliveryStatus) -> None:
        row = self.conn.execute(
            "SELECT status FROM content_item WHERE id = ?", (content_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"content_item {content_id} not found")
        src = DeliveryStatus(row["status"])
        if not is_legal_transition(src, dst):
            raise InvalidTransition(f"{src} -> {dst} (content_item {content_id})")

        sets = ["status = ?"]
        params: list[object] = [dst.value]
        if dst == DeliveryStatus.DELIVERED:
            sets.append("delivered_at = ?")
            params.append(_now())
        elif dst == DeliveryStatus.REVIEWED:
            sets.append("reviewed_at = ?")
            params.append(_now())
        params.append(content_id)
        try:
            self.conn.execute(f"UPDATE content_item SET {', '.join(sets)} WHERE id = ?", params)
            self.conn.commit()
        except sqlite3.IntegrityError as exc:  # trigger fired (defense-in-depth)
            raise InvalidTransition(str(exc)) from exc

    # ---- quizzes & attempts ------------------------------------------------
    def save_quiz(self, content_id: int, kind: QuizKind, questions: list[QuizQuestion]) -> int:
        cur = self.conn.execute(
            "INSERT INTO quiz (content_id, kind, created_at) VALUES (?, ?, ?)",
            (content_id, kind.value, _now()),
        )
        quiz_id = int(cur.lastrowid)
        for q in questions:
            qc = self.conn.execute(
                """
                INSERT INTO quiz_question
                    (quiz_id, prompt, options_json, correct_index, explanation)
                VALUES (?, ?, ?, ?, ?)
                """,
                (quiz_id, q.prompt, json.dumps(q.options), q.correct_index, q.explanation),
            )
            q.id = int(qc.lastrowid)
            q.quiz_id = quiz_id
        self.conn.commit()
        return quiz_id

    def get_quiz(self, content_id: int, kind: QuizKind) -> Quiz | None:
        qrow = self.conn.execute(
            "SELECT * FROM quiz WHERE content_id = ? AND kind = ? ORDER BY id DESC LIMIT 1",
            (content_id, kind.value),
        ).fetchone()
        if qrow is None:
            return None
        qrows = self.conn.execute(
            "SELECT * FROM quiz_question WHERE quiz_id = ? ORDER BY id", (qrow["id"],)
        ).fetchall()
        questions = [
            QuizQuestion(
                id=r["id"],
                quiz_id=r["quiz_id"],
                prompt=r["prompt"],
                options=json.loads(r["options_json"]),
                correct_index=r["correct_index"],
                explanation=r["explanation"],
            )
            for r in qrows
        ]
        return Quiz(id=qrow["id"], content_id=content_id, kind=kind, questions=questions)

    def record_attempt(
        self, quiz_question_id: int, user_id: int, chosen_index: int, is_correct: bool
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO attempt
                (quiz_question_id, user_id, chosen_index, is_correct, answered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (quiz_question_id, user_id, chosen_index, int(is_correct), _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def attempts_for_content(self, content_id: int, user_id: int) -> list[Attempt]:
        rows = self.conn.execute(
            """
            SELECT a.* FROM attempt a
            JOIN quiz_question qq ON qq.id = a.quiz_question_id
            JOIN quiz q ON q.id = qq.quiz_id
            WHERE q.content_id = ? AND a.user_id = ?
            ORDER BY a.id
            """,
            (content_id, user_id),
        ).fetchall()
        return [
            Attempt(
                id=r["id"],
                quiz_question_id=r["quiz_question_id"],
                user_id=r["user_id"],
                chosen_index=r["chosen_index"],
                is_correct=bool(r["is_correct"]),
                answered_at=r["answered_at"],
            )
            for r in rows
        ]

    # ---- vocabulary --------------------------------------------------------
    def save_vocab(self, content_id: int, items: list[VocabItem]) -> None:
        for v in items:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO vocab_item
                    (content_id, word, lemma, definition, example, freq_rank, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (content_id, v.word, v.lemma, v.definition, v.example, v.freq_rank, _now()),
            )
        self.conn.commit()

    def get_vocab(self, content_id: int) -> list[VocabItem]:
        rows = self.conn.execute(
            "SELECT * FROM vocab_item WHERE content_id = ? ORDER BY freq_rank", (content_id,)
        ).fetchall()
        return [
            VocabItem(
                id=r["id"],
                content_id=r["content_id"],
                word=r["word"],
                lemma=r["lemma"],
                definition=r["definition"],
                example=r["example"],
                freq_rank=r["freq_rank"],
            )
            for r in rows
        ]

    # ---- anki & logs -------------------------------------------------------
    def save_anki_cards(self, content_id: int, cards: list[Card], deck: str, sink: str) -> None:
        for c in cards:
            self.conn.execute(
                """
                INSERT INTO anki_card (content_id, front, back, deck, sink, exported_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (content_id, c.front, c.back, deck, sink, _now()),
            )
        self.conn.commit()

    def log_job(self, job: str, status: str, detail: str = "") -> None:
        self.conn.execute(
            "INSERT INTO schedule_log (job, run_at, status, detail) VALUES (?, ?, ?, ?)",
            (job, _now(), status, detail),
        )
        self.conn.commit()

    # ---- session errors ----------------------------------------------------
    def save_session_errors(
        self, user_id: int, session_type: str, errors: list[dict[str, str]]
    ) -> None:
        """Persist errors extracted from a speaking/coach session feedback."""
        for e in errors:
            self.conn.execute(
                """
                INSERT INTO session_error
                    (user_id, session_type, error_type, error_text, correction, context, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    session_type,
                    e.get("type", "grammar"),
                    e.get("error", ""),
                    e.get("correction", ""),
                    e.get("context", ""),
                    _now(),
                ),
            )
        self.conn.commit()

    def recent_session_errors(
        self, user_id: int, limit: int = 10, days: int = 1
    ) -> list[dict[str, str]]:
        """Return recent session errors for the user (last N days)."""
        cutoff = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        rows = self.conn.execute(
            """
            SELECT session_type, error_type, error_text, correction, context, created_at
            FROM session_error
            WHERE user_id = ? AND created_at >= ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def top_session_errors(self, user_id: int, limit: int = 5) -> list[dict[str, object]]:
        """Return the most frequent recurring errors across all sessions."""
        rows = self.conn.execute(
            """
            SELECT error_type, error_text, correction, COUNT(*) as count
            FROM session_error
            WHERE user_id = ?
            GROUP BY error_type, error_text
            ORDER BY count DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_anki_cards_today(self, user_id: int) -> list[tuple[str, str]]:
        """Return Anki cards from items delivered today only."""
        today = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        rows = self.conn.execute(
            """
            SELECT a.front, a.back FROM anki_card a
            JOIN content_item ci ON ci.id = a.content_id
            WHERE ci.user_id = ? AND ci.delivered_at >= ?
            ORDER BY a.id DESC
            """,
            (user_id, today),
        ).fetchall()
        return [(r["front"], r["back"]) for r in rows]

    # ---- essays -------------------------------------------------------------
    def save_essay(
        self, user_id: int, prompt: str, essay_text: str,
        score: int | None, feedback: str, essay_type: str,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO essay (user_id, prompt, essay_text, score, feedback, essay_type, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, prompt, essay_text, score, feedback, essay_type, _now()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def recent_essays(self, user_id: int, limit: int = 5) -> list[dict[str, object]]:
        rows = self.conn.execute(
            """
            SELECT id, prompt, essay_text, score, feedback, essay_type, created_at
            FROM essay WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def essay_count(self, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT count(*) AS c FROM essay WHERE user_id = ?", (user_id,)
        ).fetchone()
        return int(row["c"])

    def last_essay_type(self, user_id: int) -> str | None:
        """Return the essay_type of the most recent essay, or None."""
        row = self.conn.execute(
            "SELECT essay_type FROM essay WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return row["essay_type"] if row else None

    # ---- topic progress -----------------------------------------------------
    def record_topic_progress(
        self, user_id: int, topic: str, source_type: str,
        source_id: int | None = None, score: float | None = None,
    ) -> None:
        """Record a topic interaction (quiz result, session, essay)."""
        self.conn.execute(
            """
            INSERT OR REPLACE INTO topic_progress
                (user_id, topic, source_type, source_id, score, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, topic, source_type, source_id, score, _now()),
        )
        self.conn.commit()

    def weak_topics(self, user_id: int, limit: int = 5) -> list[dict[str, object]]:
        """Return topics with lowest average scores."""
        rows = self.conn.execute(
            """
            SELECT topic, AVG(score) as avg_score, COUNT(*) as count
            FROM topic_progress
            WHERE user_id = ? AND score IS NOT NULL
            GROUP BY topic
            ORDER BY avg_score ASC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def strong_topics(self, user_id: int, limit: int = 5) -> list[dict[str, object]]:
        """Return topics with highest average scores."""
        rows = self.conn.execute(
            """
            SELECT topic, AVG(score) as avg_score, COUNT(*) as count
            FROM topic_progress
            WHERE user_id = ? AND score IS NOT NULL
            GROUP BY topic
            ORDER BY avg_score DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def practice_streak(self, user_id: int) -> int:
        """Calculate consecutive days with at least one activity."""
        rows = self.conn.execute(
            """
            SELECT DISTINCT DATE(day) as day FROM (
                SELECT delivered_at as day FROM content_item
                    WHERE user_id = ? AND delivered_at IS NOT NULL
                UNION ALL
                SELECT answered_at as day FROM attempt WHERE user_id = ?
                UNION ALL
                SELECT created_at as day FROM session_error WHERE user_id = ?
                UNION ALL
                SELECT created_at as day FROM essay WHERE user_id = ?
            )
            ORDER BY day DESC
            """,
            (user_id, user_id, user_id, user_id),
        ).fetchall()
        if not rows:
            return 0
        from datetime import datetime as dt, timedelta
        streak = 0
        today = dt.now(UTC).date()
        for row in rows:
            day = dt.fromisoformat(row["day"]).date()
            expected = today - timedelta(days=streak)
            if day == expected:
                streak += 1
            elif day < expected:
                break
        return streak

    # ---- progress tracking -------------------------------------------------
    def count_status(self, user_id: int, status: DeliveryStatus) -> int:
        row = self.conn.execute(
            "SELECT count(*) AS c FROM content_item WHERE user_id = ? AND status = ?",
            (user_id, status.value),
        ).fetchone()
        return int(row["c"])

    def anki_card_count(self, user_id: int) -> int:
        row = self.conn.execute(
            "SELECT count(*) AS c FROM anki_card a "
            "JOIN content_item ci ON ci.id = a.content_id WHERE ci.user_id = ?",
            (user_id,),
        ).fetchone()
        return int(row["c"])

    def get_anki_cards(self, user_id: int, limit: int = 300) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT a.front, a.back FROM anki_card a "
            "JOIN content_item ci ON ci.id = a.content_id WHERE ci.user_id = ? "
            "ORDER BY a.id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [(r["front"], r["back"]) for r in rows]

    # ---- helpers -----------------------------------------------------------
    @staticmethod
    def _to_content(row: sqlite3.Row) -> ContentItem:
        return ContentItem(**dict(row))
