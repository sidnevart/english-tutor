-- english-tutor schema. SQLite is the source of truth for catalog eligibility,
-- daily plans, attempts, deadlines, scores, and the dynamic learning profile.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subscriber (
    user_id    INTEGER PRIMARY KEY,
    joined_at  TEXT NOT NULL,
    prefs_json TEXT NOT NULL DEFAULT '{}'   -- calendar anchors and user preferences
);

CREATE TABLE IF NOT EXISTS session_error (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    session_type TEXT NOT NULL,             -- legacy speaking/writing session type
    error_type   TEXT NOT NULL,             -- grammar | vocab | phrasing
    error_text   TEXT NOT NULL,
    correction   TEXT NOT NULL,
    context      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_session_error_user ON session_error (user_id, created_at);

CREATE TABLE IF NOT EXISTS catalog_task (
    id               TEXT PRIMARY KEY,
    version          INTEGER NOT NULL,
    section          TEXT NOT NULL,
    task_type        TEXT NOT NULL,
    topic_domain     TEXT NOT NULL,
    cefr             TEXT NOT NULL,
    skill_tags_json  TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    explanation      TEXT NOT NULL DEFAULT '',
    provenance       TEXT NOT NULL,
    source_url       TEXT,
    source_date      TEXT,
    validation_state TEXT NOT NULL,
    eligible         INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_catalog_task_rotation
    ON catalog_task (section, task_type, eligible, validation_state);

CREATE TABLE IF NOT EXISTS daily_plan (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    plan_date   TEXT NOT NULL,
    section     TEXT NOT NULL,
    task_id     TEXT NOT NULL REFERENCES catalog_task(id),
    status      TEXT NOT NULL DEFAULT 'not_started',
    notified_at TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, plan_date, section)
);

CREATE INDEX IF NOT EXISTS ix_daily_plan_user_date ON daily_plan (user_id, plan_date);

CREATE TABLE IF NOT EXISTS practice_attempt (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    plan_id          INTEGER REFERENCES daily_plan(id),
    task_id          TEXT NOT NULL REFERENCES catalog_task(id),
    status           TEXT NOT NULL DEFAULT 'active',
    current_item     INTEGER NOT NULL DEFAULT 0,
    started_at       TEXT NOT NULL,
    deadline_at      TEXT,
    completed_at     TEXT,
    raw_score        REAL,
    max_score        REAL,
    evaluation_state TEXT NOT NULL DEFAULT 'not_needed',
    feedback_json    TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_active_attempt_user
    ON practice_attempt (user_id) WHERE status = 'active';

CREATE UNIQUE INDEX IF NOT EXISTS ux_attempt_plan
    ON practice_attempt (plan_id) WHERE plan_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS callback_receipt (
    callback_id TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempt_item (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id     INTEGER NOT NULL REFERENCES practice_attempt(id) ON DELETE CASCADE,
    item_index     INTEGER NOT NULL,
    response_text  TEXT NOT NULL DEFAULT '',
    response_json  TEXT NOT NULL DEFAULT '{}',
    correct_json   TEXT NOT NULL DEFAULT '{}',
    score          REAL,
    max_score      REAL,
    feedback_json  TEXT NOT NULL DEFAULT '{}',
    metrics_json   TEXT NOT NULL DEFAULT '{}',
    submitted_at   TEXT NOT NULL,
    UNIQUE (attempt_id, item_index)
);

CREATE TABLE IF NOT EXISTS learning_issue (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    canonical_key     TEXT NOT NULL,
    section           TEXT NOT NULL,
    category          TEXT NOT NULL,
    skill_code        TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'new',
    severity          INTEGER NOT NULL DEFAULT 1,
    evaluator_confidence REAL NOT NULL DEFAULT 1.0,
    original_excerpt  TEXT NOT NULL DEFAULT '',
    correction        TEXT NOT NULL DEFAULT '',
    explanation       TEXT NOT NULL DEFAULT '',
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    success_dates_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE (user_id, canonical_key)
);

CREATE TABLE IF NOT EXISTS issue_event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id    INTEGER NOT NULL REFERENCES learning_issue(id) ON DELETE CASCADE,
    attempt_id  INTEGER REFERENCES practice_attempt(id),
    event_type  TEXT NOT NULL,
    local_date  TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    legacy_session_error_id INTEGER,
    created_at  TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_issue_event_legacy
    ON issue_event (legacy_session_error_id) WHERE legacy_session_error_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS skill_stat (
    user_id       INTEGER NOT NULL,
    skill_code    TEXT NOT NULL,
    section       TEXT NOT NULL,
    opportunities INTEGER NOT NULL DEFAULT 0,
    successes     INTEGER NOT NULL DEFAULT 0,
    accuracy      REAL NOT NULL DEFAULT 0,
    trend         REAL NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, skill_code)
);

CREATE TABLE IF NOT EXISTS catalog_generation_run (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url       TEXT,
    task_type        TEXT,
    status           TEXT NOT NULL,
    validation_json  TEXT NOT NULL DEFAULT '[]',
    diagnostics_json TEXT NOT NULL DEFAULT '{}',
    started_at       TEXT NOT NULL,
    completed_at     TEXT
);

CREATE TABLE IF NOT EXISTS schedule_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job    TEXT NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
