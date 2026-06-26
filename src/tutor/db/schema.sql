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
    explanation   TEXT NOT NULL DEFAULT '',
    correct_indices_json TEXT NOT NULL DEFAULT ''  -- JSON int array for multi-select (summary)
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

CREATE TABLE IF NOT EXISTS session_error (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    session_type TEXT NOT NULL,                     -- speak | discuss | coach
    error_type  TEXT NOT NULL,                      -- grammar | vocab | phrasing
    error_text  TEXT NOT NULL,
    correction  TEXT NOT NULL,
    context     TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_session_error_user ON session_error (user_id, created_at);

CREATE TABLE IF NOT EXISTS essay (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    prompt      TEXT NOT NULL,
    essay_text  TEXT NOT NULL,
    score       INTEGER,                            -- 0-5 TOEFL writing rubric
    feedback    TEXT NOT NULL,
    essay_type  TEXT NOT NULL,                       -- independent | integrated | email
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_essay_user ON essay (user_id, created_at);

CREATE TABLE IF NOT EXISTS speaking_attempt (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    task_type   TEXT NOT NULL,                       -- independent | campus | concept | lecture
    prompt      TEXT NOT NULL,
    transcript  TEXT NOT NULL DEFAULT '',
    delivery    INTEGER,                             -- 0-4 rubric sub-score
    language_use INTEGER,                            -- 0-4 rubric sub-score
    topic_dev   INTEGER,                             -- 0-4 rubric sub-score
    score       INTEGER,                             -- overall 0-4
    scaled_30   INTEGER,                             -- estimated 0-30 scaled score
    feedback    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_speaking_user ON speaking_attempt (user_id, created_at);

CREATE TABLE IF NOT EXISTS topic_progress (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    topic       TEXT NOT NULL,                       -- e.g. "science", "economics", "culture"
    source_type TEXT NOT NULL,                       -- quiz | session | essay
    source_id   INTEGER,                             -- content_id or session id
    score       REAL,                                -- 0.0-1.0 (quiz % or qualitative)
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, topic, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS ix_topic_user ON topic_progress (user_id, topic);

CREATE TABLE IF NOT EXISTS worksheet (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    items_json  TEXT NOT NULL,                       -- JSON: all exercise items
    answers     TEXT NOT NULL DEFAULT '',             -- user answers (when submitted)
    score       REAL,                                -- total score 0.0-1.0
    feedback    TEXT NOT NULL DEFAULT '',             -- LLM feedback
    status      TEXT NOT NULL DEFAULT 'pending'       -- pending | submitted | graded
);

CREATE INDEX IF NOT EXISTS ix_worksheet_user ON worksheet (user_id, created_at);

-- Writing task files: a generated TOEFL writing prompt the learner fills in and
-- sends back as a file (not same-day). The submitted essay is then graded and
-- stored in the `essay` table; this row tracks the pending prompt + its sources.
CREATE TABLE IF NOT EXISTS writing_task (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    essay_type  TEXT NOT NULL,                       -- independent | integrated | email
    prompt      TEXT NOT NULL,
    passage     TEXT NOT NULL DEFAULT '',             -- reading passage (integrated)
    lecture     TEXT NOT NULL DEFAULT '',             -- lecture transcript (integrated; audio-only)
    status      TEXT NOT NULL DEFAULT 'pending',      -- pending | submitted
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_writing_task_user ON writing_task (user_id, created_at);

-- Per-channel scrape watermarks: track newest and oldest message IDs seen
-- so each daily run picks up new posts and continues backfilling history.
CREATE TABLE IF NOT EXISTS channel_watermark (
    channel_ref    TEXT PRIMARY KEY,       -- str(channel_id)
    max_scraped_id INTEGER NOT NULL DEFAULT 0,  -- newest message ID seen
    min_scraped_id INTEGER,                -- oldest message ID seen (NULL = first run)
    last_run_at    TEXT NOT NULL DEFAULT ''
);
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
