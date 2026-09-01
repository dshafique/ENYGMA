-- The Friday note.
--
-- One row per ISO week, kept forever. Kept, not regenerated on demand, for two
-- reasons: the material it was written from moves (an action closed on Monday
-- can be reopened on Tuesday), and after a few months the rows are the only
-- dated, factual record he has of what he actually did. That record is the
-- point of the feature, not a side effect of it.
--
-- body is what was generated. edited is what he changed it to, and is NULL until
-- he changes something -- so a re-roll can replace the generated half without
-- silently throwing away his edit, and the interface can offer it back.
CREATE TABLE IF NOT EXISTS week_notes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start    TEXT NOT NULL UNIQUE,   -- the Monday, as YYYY-MM-DD, local
    week_end      TEXT NOT NULL,          -- the Friday, as YYYY-MM-DD, local
    body          TEXT NOT NULL,          -- JSON: {"done": [...], "next": [...]}
    edited        TEXT,                   -- JSON, same shape, his version
    drawn_from    TEXT,                   -- the one-line provenance, in words
    sources       TEXT,                   -- JSON: the ids it actually read
    model         TEXT,
    generated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    edited_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_week_notes_start ON week_notes(week_start DESC);
