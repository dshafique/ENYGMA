-- 004_workspace.sql
-- The surfaces beyond Meetings: Directory, Chat, the glossary behind the term
-- popover, and the Home tidbits. Forever-additive, like the three before it.

-- Directory. A person is created the first time a speaker label is assigned a
-- name, and never merged automatically: two similar names are two people.
CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    role        TEXT,
    org         TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Chat. One thread per subject so a term can open its own conversation and the
-- history stays legible later.
CREATE TABLE IF NOT EXISTS chat_threads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    seed_term     TEXT,
    recording_id  INTEGER REFERENCES recordings(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,          -- operator | enygma
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id, id);

-- The glossary behind the hold-a-word popover. A miss is not an error: the
-- popover says it does not know the term yet and offers to ask.
CREATE TABLE IF NOT EXISTS terms (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    term        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,   -- lowercased, for lookup
    gloss       TEXT NOT NULL,
    kind        TEXT,                   -- protocol | tool | method | concept
    asked_count INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- What ENYGMA has noticed about how he works. Written by the app, read on Home.
CREATE TABLE IF NOT EXISTS observations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,          -- strength | gap | pattern
    body        TEXT NOT NULL,
    evidence    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Up to three headlines in his realm. Populated by a feed job that does not
-- exist yet; the table is here so Home has somewhere real to read from.
CREATE TABLE IF NOT EXISTS tidbits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    headline    TEXT NOT NULL,
    source      TEXT,
    url         TEXT,
    topic       TEXT,                   -- computing | physics
    published   TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tidbits_fetched ON tidbits(fetched_at DESC);
