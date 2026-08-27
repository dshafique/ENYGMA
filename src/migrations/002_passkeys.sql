-- 002_passkeys.sql
-- Passkeys, the PIN fallback and recovery codes.

CREATE TABLE IF NOT EXISTS credentials (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    credential_id  BLOB NOT NULL UNIQUE,
    public_key     BLOB NOT NULL,
    sign_count     INTEGER NOT NULL DEFAULT 0,
    transports     TEXT,
    device_name    TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at   TEXT,
    revoked_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_credentials_live ON credentials(revoked_at);

-- Challenges live server side, are single use, and expire. A challenge that
-- round-trips through anything the client can edit is the whole attack.
CREATE TABLE IF NOT EXISTS challenges (
    id          TEXT PRIMARY KEY,
    challenge   BLOB NOT NULL,
    purpose     TEXT NOT NULL,          -- register | authenticate
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL,
    consumed_at TEXT
);

CREATE TABLE IF NOT EXISTS pin (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    hash        TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recovery_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hash        TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    used_at     TEXT
);

-- One counter for both methods. Five total, not five each.
CREATE TABLE IF NOT EXISTS auth_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL DEFAULT (datetime('now')),
    method      TEXT NOT NULL,          -- passkey | pin | recovery
    ok          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_auth_attempts_at ON auth_attempts(at DESC);
