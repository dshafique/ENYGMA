"""PIN and recovery codes. Argon2id, never a fast hash.

Nothing in this module ever returns a secret, logs one, or puts one in an error.
"""
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from ..config import config
from ..db import cursor

_ph = PasswordHasher()

# No O, 0, I or 1. This gets written on paper.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def set_pin(pin: str) -> None:
    low, high = config.PIN_MIN_DIGITS, config.PIN_MAX_DIGITS
    if not pin.isdigit() or not (low <= len(pin) <= high):
        raise ValueError(f"PIN must be {low} to {high} digits")
    if len(set(pin)) == 1:
        raise ValueError("A PIN of one repeated digit is not a PIN")
    with cursor() as conn:
        conn.execute(
            "INSERT INTO pin (id, hash, updated_at) VALUES (1, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET hash = excluded.hash, updated_at = datetime('now')",
            (_ph.hash(pin),),
        )


def has_pin() -> bool:
    with cursor() as conn:
        return conn.execute("SELECT 1 FROM pin WHERE id = 1").fetchone() is not None


def clear_pin() -> None:
    with cursor() as conn:
        conn.execute("DELETE FROM pin WHERE id = 1")


def verify_pin(pin: str) -> bool:
    with cursor() as conn:
        row = conn.execute("SELECT hash FROM pin WHERE id = 1").fetchone()
    if not row:
        return False
    try:
        return _ph.verify(row["hash"], pin)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_recovery_codes(groups: int = 6, size: int = 4) -> list[str]:
    """Returns the plaintext once. The caller shows it once and never stores it."""
    codes = [
        "".join(secrets.choice(ALPHABET) for _ in range(size)) for _ in range(groups)
    ]
    with cursor() as conn:
        conn.execute("DELETE FROM recovery_codes WHERE used_at IS NULL")
        for code in codes:
            conn.execute("INSERT INTO recovery_codes (hash) VALUES (?)", (_ph.hash(code),))
    return codes


def consume_recovery_code(code: str) -> bool:
    code = code.strip().upper()
    with cursor() as conn:
        for row in conn.execute("SELECT id, hash FROM recovery_codes WHERE used_at IS NULL"):
            try:
                if _ph.verify(row["hash"], code):
                    conn.execute(
                        "UPDATE recovery_codes SET used_at = datetime('now') WHERE id = ?",
                        (row["id"],),
                    )
                    return True
            except (VerifyMismatchError, InvalidHashError):
                continue
    return False


# --------------------------------------------------------------------------
# Setup codes, for enrolling a second device
# --------------------------------------------------------------------------
PAIRING_MINUTES = 10


def _format(raw: str) -> str:
    """ABCD-EFGH. Read aloud across a room without ambiguity."""
    return f"{raw[:4]}-{raw[4:]}"


def create_pairing_code(note: str | None = None) -> dict:
    """Plaintext once, to be shown once. Only the hash is kept.

    Any code still outstanding is cancelled: two live codes means one of them is
    forgotten, and a forgotten credential is the one that gets used against you.
    """
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    with cursor() as conn:
        conn.execute("DELETE FROM pairing_codes WHERE used_at IS NULL")
        conn.execute(
            "INSERT INTO pairing_codes (hash, note, expires_at) "
            "VALUES (?, ?, datetime('now', ?))",
            (_ph.hash(raw), note, f"+{PAIRING_MINUTES} minutes"),
        )
    return {"code": _format(raw), "minutes": PAIRING_MINUTES}


def consume_pairing_code(code: str, used_by: str | None = None) -> bool:
    """Single use, and only while it is alive."""
    cleaned = (code or "").strip().upper().replace("-", "").replace(" ", "")
    if len(cleaned) != 8:
        return False
    with cursor() as conn:
        rows = list(conn.execute(
            "SELECT id, hash FROM pairing_codes "
            "WHERE used_at IS NULL AND expires_at > datetime('now')"))
        for row in rows:
            try:
                if _ph.verify(row["hash"], cleaned):
                    conn.execute(
                        "UPDATE pairing_codes SET used_at = datetime('now'), used_by = ? "
                        "WHERE id = ?", (used_by, row["id"]))
                    return True
            except (VerifyMismatchError, InvalidHashError):
                continue
    return False


def pairing_outstanding() -> bool:
    with cursor() as conn:
        return conn.execute(
            "SELECT 1 FROM pairing_codes WHERE used_at IS NULL "
            "AND expires_at > datetime('now')").fetchone() is not None
