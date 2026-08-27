-- 003_uploads_and_pipeline.sql
-- Audio arrives by drag and drop, not from a recorder poller. The HiNotes columns
-- stay: migrations are forever-additive, and the poller is gated off, not deleted.

ALTER TABLE recordings ADD COLUMN sha256 TEXT;
ALTER TABLE recordings ADD COLUMN source TEXT NOT NULL DEFAULT 'upload';
ALTER TABLE recordings ADD COLUMN original_filename TEXT;
ALTER TABLE recordings ADD COLUMN mime TEXT;
ALTER TABLE recordings ADD COLUMN transcribed_at TEXT;
ALTER TABLE recordings ADD COLUMN model TEXT;

-- Content addressed, so dropping the same file twice is one recording.
CREATE UNIQUE INDEX IF NOT EXISTS idx_recordings_sha ON recordings(sha256)
    WHERE sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS transcript_segments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,
    speaker_label TEXT,
    start_ms      INTEGER,
    end_ms        INTEGER,
    text          TEXT NOT NULL,
    edited_at     TEXT,
    original_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_segments_recording ON transcript_segments(recording_id, idx);

-- Speaker labels start as SPEAKER 1 and are assigned by hand. Exact only:
-- two people with similar names are two people.
CREATE TABLE IF NOT EXISTS speakers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    label         TEXT NOT NULL,
    person_name   TEXT,
    turns         INTEGER NOT NULL DEFAULT 0,
    UNIQUE (recording_id, label)
);

CREATE TABLE IF NOT EXISTS summaries (
    recording_id  INTEGER PRIMARY KEY REFERENCES recordings(id) ON DELETE CASCADE,
    abstract      TEXT,
    decisions     TEXT,   -- json array of {text, at_ms}
    questions     TEXT,   -- json array of {text, at_ms}
    model         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS action_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id  INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    text          TEXT NOT NULL,
    owner         TEXT,
    due_date      TEXT,
    at_ms         INTEGER,
    done_at       TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_actions_open ON action_items(done_at);
