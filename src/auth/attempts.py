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
        row = conn.execute(
            "SELECT CAST((julianday('now') - julianday(?)) * 86400 AS INTEGER) AS s",
            (rows[0]["at"],),
        ).fetchone()
        elapsed = row["s"] or 0
        return max(0, config.LOCKOUT_SECONDS - elapsed)


def failures() -> int:
    with cursor() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM auth_attempts WHERE ok = 0").fetchone()
        return row["n"]
