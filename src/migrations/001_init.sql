-- 001_init.sql
-- Migrations are forever-additive. Never drop, never rename. Reversibility is a
-- tenet, not a nicety: to remove a column, stop writing to it.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One operator. The row exists so foreign keys have something to point at, not
-- because this is ever multi-tenant.
CREATE TABLE IF NOT EXISTS operator (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    handle      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recordings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     TEXT UNIQUE,              -- HiNotes noteId
    title         TEXT NOT NULL,
    recorded_at   TEXT,
    duration_ms   INTEGER,
    audio_path    TEXT,
    bytes         INTEGER,
    status        TEXT NOT NULL DEFAULT 'queued',
                  -- queued | transcribing | ready | failed | merged
    failure       TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recordings_recorded_at ON recordings(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_recordings_status      ON recordings(status);

CREATE TABLE IF NOT EXISTS ingest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ran_at      TEXT NOT NULL DEFAULT (datetime('now')),
    outcome     TEXT NOT NULL,   -- pulled | nothing_new | credentials_expired | error
    detail      TEXT,
    count       INTEGER NOT NULL DEFAULT 0
);
