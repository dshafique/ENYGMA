"""One attempt counter for passkey, PIN and recovery together.

Five total, not five each, and the lockout is server side and keyed on the account.
A client-side countdown is decoration.
"""
from ..config import config
from ..db import cursor

WINDOW_SQL = "datetime('now', ?)"


def record(method: str, ok: bool) -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO auth_attempts (method, ok) VALUES (?, ?)", (method, 1 if ok else 0)
        )
        if ok:
            conn.execute("DELETE FROM auth_attempts WHERE ok = 0")


def penalty_seconds(failed: int) -> int:
    """How long this round of failures is worth.

    Flat delays are the wrong shape for a short PIN. Five wrong tries is a fat
    finger and costs thirty seconds; fifty wrong tries is not a person and costs
    an hour. Doubling each round means an exhaustive search of a four digit PIN
    runs out of human lifetime, while a genuine mistake never costs more than the
    first thirty seconds.
    """
    rounds = max(0, failed // config.MAX_ATTEMPTS - 1)
    return min(config.LOCKOUT_SECONDS * (2 ** rounds), config.LOCKOUT_MAX_SECONDS)


def lockout_remaining() -> int:
    """Seconds remaining, or 0."""
    with cursor() as conn:
        rows = list(
            conn.execute(
                "SELECT at FROM auth_attempts WHERE ok = 0 ORDER BY at DESC LIMIT ?",
                (config.MAX_ATTEMPTS,),
            )
        )
        if len(rows) < config.MAX_ATTEMPTS:
            return 0
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM auth_attempts WHERE ok = 0").fetchone()["n"]
        row = conn.execute(
            "SELECT CAST((julianday('now') - julianday(?)) * 86400 AS INTEGER) AS s",
            (rows[0]["at"],),
        ).fetchone()
        elapsed = row["s"] or 0
        return max(0, penalty_seconds(total) - elapsed)


def failures() -> int:
    with cursor() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM auth_attempts WHERE ok = 0").fetchone()
        return row["n"]
