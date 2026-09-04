-- The bench: the things he writes down himself.
--
-- Everything else in this application is derived. Meetings come from audio,
-- actions come from meetings, the week's note comes from both. These two tables
-- are the only places where what is stored is simply what he typed, which is
-- why they sit together behind one tab.
--
-- Two states on the backlog, not four, because there are two people and one of
-- them is maintenance. `note` is what makes two states survivable: when an entry
-- is crossed off, the line saying why is the difference between "he fixed it"
-- and "he decided against it", and without it neither of them will remember.
CREATE TABLE IF NOT EXISTS bench_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'bug',   -- bug | idea | todo
    text        TEXT NOT NULL,
    done        INTEGER NOT NULL DEFAULT 0,
    note        TEXT,                          -- why it was crossed off
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    done_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_bench_open ON bench_entries(done, id DESC);

-- Notes are his. Nothing here is summarised, scored or sent to a model, and
-- nothing here is searched by Chat. Anything he wants ENYGMA to be able to
-- quote back belongs in the Library instead, which is a different promise and
-- deserves a different place.
CREATE TABLE IF NOT EXISTS bench_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL DEFAULT 'Untitled',
    body        TEXT NOT NULL DEFAULT '',
    pinned      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bench_notes ON bench_notes(pinned DESC, updated_at DESC);
