-- What the paid models have cost, so far.
--
-- ENYGMA cannot see the bill. Anthropic can, at the end of the month, and by
-- then the money is spent. So it keeps its own count from the token figures the
-- API returns on every call, and says something the moment the count crosses a
-- round number.
--
-- One row per call rather than a running total, because a total is a number
-- nobody can check. With the rows, a surprising month can be read back call by
-- call and the cause found.
CREATE TABLE IF NOT EXISTS spend (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    provider       TEXT NOT NULL,           -- anthropic | google
    model          TEXT NOT NULL,
    what           TEXT NOT NULL,           -- chat | document | weeknote
    thread_id      INTEGER,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    -- Tenths of a cent. Integers, because a month of floating point addition
    -- drifts and this number is shown to him as money.
    cost_millicents INTEGER NOT NULL DEFAULT 0,
    at             TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_spend_month ON spend(provider, at);

-- The highest round number he has already been told about, per provider per
-- month. Without it he is told about the same ten dollars on every answer for
-- the rest of the month, which is how a useful warning becomes noise he learns
-- to scroll past.
CREATE TABLE IF NOT EXISTS spend_warnings (
    provider   TEXT NOT NULL,
    month      TEXT NOT NULL,        -- YYYY-MM, local
    told_at    INTEGER NOT NULL,     -- millicents of the highest step reported
    PRIMARY KEY (provider, month)
);
