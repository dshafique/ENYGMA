"""Action items across every meeting.

The Meetings tab answers "what happened in this one". This answers "what do I owe
anybody", which is a different question and deserves its own surface.
"""
from .db import cursor

_SELECT = (
    "SELECT a.id, a.text, a.owner, a.due_date, a.at_ms, a.done_at, a.created_at, "
    "       a.recording_id, r.title AS meeting, r.recorded_at, "
    "       (SELECT s.person_name FROM speakers s "
    "        WHERE s.recording_id = a.recording_id AND s.label = a.owner) AS owner_name "
    "FROM action_items a JOIN recordings r ON r.id = a.recording_id "
)


def listing(include_done: bool = True) -> dict:
    where = "" if include_done else "WHERE a.done_at IS NULL "
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            _SELECT + where + "ORDER BY a.done_at IS NOT NULL, r.recorded_at DESC, a.id"
        )]
    return {
        "open": [r for r in rows if not r["done_at"]],
        "done": [r for r in rows if r["done_at"]],
        "total": len(rows),
    }


def open_count() -> int:
    with cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM action_items WHERE done_at IS NULL"
        ).fetchone()
    return row["n"] if row else 0
