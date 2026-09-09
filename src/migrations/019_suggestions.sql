-- Work nobody has picked up.
--
-- Every action item in this app came from someone saying they would do a thing.
-- This is the other half: the things a meeting left on the floor. A question
-- raised and never answered, a decision Luigi asked for twice, a gap sitting
-- between two people's work that both assumed the other had.
--
-- These are guesses, and they are stored apart from action_items on purpose.
-- An action item is a commitment; a suggestion is ENYGMA noticing something.
-- Putting them in one table would mean one careless join away from a guess
-- appearing in his list of obligations, which is the exact failure this feature
-- has to avoid: he must never tell his manager he is doing something because a
-- machine implied he owed it.
--
-- A suggestion becomes real only by being taken, and taking it writes an
-- ordinary row into action_items with his name on it. From that moment it is a
-- commitment and looks like one, because it is one.
CREATE TABLE IF NOT EXISTS suggestions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    gap           TEXT NOT NULL,        -- what nobody is holding, as a fact
    could         TEXT NOT NULL,        -- the move, phrased as "you could"
    recording_id  INTEGER REFERENCES recordings(id) ON DELETE CASCADE,
    at_ms         INTEGER,              -- where in the meeting it is visible
    state         TEXT NOT NULL DEFAULT 'offered',   -- offered | taken | passed
    state_at      TEXT,
    action_id     INTEGER REFERENCES action_items(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_suggestions_live ON suggestions(state, created_at);
