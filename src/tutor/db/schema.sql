-- english-tutor schema. SQLite is the source of truth for the learner's
-- error diary and scheduler diagnostics. The bot's whole purpose is capturing
-- speaking/writing errors into `session_error`; everything else is plumbing.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subscriber (
    user_id    INTEGER PRIMARY KEY,
    joined_at  TEXT NOT NULL,
    prefs_json TEXT NOT NULL DEFAULT '{}'   -- push alternation, topic index, etc.
);

CREATE TABLE IF NOT EXISTS session_error (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    session_type TEXT NOT NULL,             -- speak | write | coach
    error_type   TEXT NOT NULL,             -- grammar | vocab | phrasing
    error_text   TEXT NOT NULL,
    correction   TEXT NOT NULL,
    context      TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_session_error_user ON session_error (user_id, created_at);

CREATE TABLE IF NOT EXISTS schedule_log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    job    TEXT NOT NULL,
    run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
