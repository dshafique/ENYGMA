"""PIN and recovery codes. Argon2id, never a fast hash.

Nothing in this module ever returns a secret, logs one, or puts one in an error.
"""
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

from ..db import cursor

_ph = PasswordHasher()

# No O, 0, I or 1. This gets written on paper.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def set_pin(pin: str) -> None:
    if not (pin.isdigit() and len(pin) == 6):
        raise ValueError("PIN must be exactly six digits")
    with cursor() as conn:
        conn.execute(
            "INSERT INTO pin (id, hash, updated_at) VALUES (1, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET hash = excluded.hash, updated_at = datetime('now')",
            (_ph.hash(pin),),
        )


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
