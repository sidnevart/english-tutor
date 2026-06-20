-- english-tutor schema. SQLite is the strict source of truth for metadata,
-- scheduling, and the NEW -> DELIVERED -> REVIEWED delivery state machine.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subscriber (
    user_id    INTEGER PRIMARY KEY,
    joined_at  TEXT NOT NULL,
    prefs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS content_item (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    source_type   TEXT NOT NULL,                 -- channel | rss
    source_ref    TEXT NOT NULL,                 -- channel id or feed name
    external_id   TEXT NOT NULL,                 -- stable dedup key
    content_type  TEXT NOT NULL,                 -- article | podcast
    title         TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    body_text     TEXT NOT NULL DEFAULT '',      -- empty until podcast is transcribed
    audio_url     TEXT NOT NULL DEFAULT '',
    duration_sec  INTEGER,
    lang          TEXT NOT NULL DEFAULT 'en',
    cadence_bucket TEXT,                          -- daily | thrice | weekend | NULL
    status        TEXT NOT NULL DEFAULT 'NEW',
    fetched_at    TEXT NOT NULL,
    delivered_at  TEXT,
    reviewed_at   TEXT,
    body_hash     TEXT NOT NULL DEFAULT '',     -- cross-source dedup key
    UNIQUE (source_ref, external_id)
);

CREATE INDEX IF NOT EXISTS ix_content_status ON content_item (user_id, status);
CREATE INDEX IF NOT EXISTS ix_content_body_hash ON content_item (user_id, body_hash);

CREATE TABLE IF NOT EXISTS quiz (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES content_item (id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                    -- reading | vocab
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quiz_question (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_id       INTEGER NOT NULL REFERENCES quiz (id) ON DELETE CASCADE,
    prompt        TEXT NOT NULL,
    options_json  TEXT NOT NULL,                 -- JSON array of strings
    correct_index INTEGER NOT NULL,
    explanation   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS vocab_item (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES content_item (id) ON DELETE CASCADE,
    word       TEXT NOT NULL,
    lemma      TEXT NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    example    TEXT NOT NULL DEFAULT '',
    freq_rank  REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (content_id, word)
);

CREATE TABLE IF NOT EXISTS attempt (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    quiz_question_id INTEGER NOT NULL REFERENCES quiz_question (id) ON DELETE CASCADE,
    user_id          INTEGER NOT NULL,
    chosen_index     INTEGER NOT NULL,
    is_correct       INTEGER NOT NULL,
    answered_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anki_card (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id  INTEGER NOT NULL REFERENCES content_item (id) ON DELETE CASCADE,
    front       TEXT NOT NULL,
    back        TEXT NOT NULL,
    deck        TEXT NOT NULL,
    sink        TEXT NOT NULL,
    exported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job    TEXT NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);

-- Defense-in-depth: reject illegal content_item status transitions at the DB
-- layer, mirroring LEGAL_TRANSITIONS in domain/enums.py.
CREATE TRIGGER IF NOT EXISTS trg_content_status_guard
BEFORE UPDATE OF status ON content_item
FOR EACH ROW
WHEN NEW.status <> OLD.status AND NOT (
       (OLD.status = 'NEW'       AND NEW.status IN ('DELIVERED', 'SKIPPED', 'FAILED'))
    OR (OLD.status = 'DELIVERED' AND NEW.status IN ('REVIEWED', 'SKIPPED', 'FAILED'))
    OR (OLD.status = 'SKIPPED'   AND NEW.status = 'NEW')
    OR (OLD.status = 'FAILED'    AND NEW.status = 'NEW')
)
BEGIN
    SELECT RAISE(ABORT, 'illegal content_item status transition');
END;
