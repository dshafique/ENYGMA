-- 005_pairing.sql
-- Enrolling a second device.
--
-- A passkey is bound to the device that made it, so a new phone has no way in.
-- Sharing the PIN with it works and is what people do, which is exactly the
-- problem: the standing secret ends up typed on more devices over time. A setup
-- code is single use, expires in minutes, and only ever buys the right to enrol
-- one passkey.

CREATE TABLE IF NOT EXISTS pairing_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hash        TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    used_at     TEXT,
    used_by     TEXT
);

CREATE INDEX IF NOT EXISTS idx_pairing_live ON pairing_codes(used_at, expires_at);
