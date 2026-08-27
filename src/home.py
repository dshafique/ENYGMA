"""Home.

The one screen that answers "what should I look at now". Everything on it is a
door into another tab; nothing lives here alone.
"""
from .db import cursor
from . import actions as actions_repo


def dashboard() -> dict:
    with cursor() as conn:
        counts = dict(conn.execute(
            "SELECT COUNT(*) AS total, "
            "  SUM(status = 'ready') AS ready, "
            "  SUM(status IN ('queued','transcribing')) AS running, "
            "  SUM(status = 'failed') AS failed "
            "FROM recordings").fetchone())
        recent = [dict(r) for r in conn.execute(
            "SELECT id, title, status, duration_ms, recorded_at, created_at "
            "FROM recordings ORDER BY COALESCE(recorded_at, created_at) DESC LIMIT 4")]
        week = conn.execute(
            "SELECT COALESCE(SUM(duration_ms), 0) AS ms FROM recordings "
            "WHERE COALESCE(recorded_at, created_at) >= datetime('now', '-7 days')"
        ).fetchone()["ms"]
        tidbits = [dict(r) for r in conn.execute(
            "SELECT * FROM tidbits ORDER BY fetched_at DESC, id DESC LIMIT 3")]
        observations = [dict(r) for r in conn.execute(
            "SELECT * FROM observations ORDER BY id DESC LIMIT 3")]
        people = conn.execute(
            "SELECT COUNT(DISTINCT person_name) AS n FROM speakers "
            "WHERE person_name IS NOT NULL AND TRIM(person_name) <> ''").fetchone()["n"]
    open_actions = actions_repo.listing(include_done=False)["open"]
    return {
        "counts": {k: (v or 0) for k, v in counts.items()},
        "recent": recent,
        "week_ms": week or 0,
        "tidbits": tidbits,
        "observations": observations,
        "people": people,
        "open_actions": open_actions[:5],
        "open_action_count": len(open_actions),
    }
