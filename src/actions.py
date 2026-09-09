"""Action items across every meeting.

The Meetings tab answers "what happened in this one". This answers "what do I owe
anybody", which is a different question and deserves its own surface.
"""
from .config import config
from .db import cursor

# An action item is not a checkbox. Declining something and not having got to it
# yet are different answers, and a list that cannot tell them apart stops being
# read. Order is the order they appear on the page.
STATES = ("open", "pending", "done", "rejected")
STATE_LABELS = {
    "open": "Open",
    "pending": "Pending",       # waiting on somebody or something else
    "done": "Done",
    "rejected": "Rejected",     # consciously turned down, on purpose
}

_SELECT = (
    "SELECT a.id, a.text, a.owner, a.due_date, a.at_ms, a.done_at, a.created_at, "
    "       a.state, a.state_at, a.state_note, "
    "       a.recording_id, r.title AS meeting, r.recorded_at, "
    "       (SELECT s.person_name FROM speakers s "
    "        WHERE s.recording_id = a.recording_id AND s.label = a.owner) AS owner_name "
    "FROM action_items a JOIN recordings r ON r.id = a.recording_id "
)


# Who owns a thing, from his point of view. "ours" is deliberately grouped with
# his own: a meeting produces a run of commitments the group made together, and
# those are his to chase as much as anything with his name on it. A filter that
# put them under "theirs" would hide half of what he actually owes.
WHO = (("mine",   "Mine"),
       ("theirs", "Theirs"))


def _is_his(row: dict) -> bool:
    """His, or the group's. An item with nobody's name on it is not somebody
    else's -- it is either the team's or nobody has claimed it, and in both
    cases it is his problem until someone says otherwise."""
    owner = (row.get("owner_name") or row.get("owner") or "").strip()
    if not owner:
        return True
    mine = config.OWNER_NAME
    return bool(mine) and owner.casefold() == mine.casefold()


def listing(include_done: bool = True, who: str | None = None) -> dict:
    where = "" if include_done else "WHERE a.state = 'open' "
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            _SELECT + where + "ORDER BY r.recorded_at DESC, a.id")]

    # Counted before the filter, always. A count that moves with the filter is
    # not a count, and this went wrong once already on the Bench.
    tally = {key: sum(1 for r in rows if _is_his(r) == (key == "mine"))
             for key, _ in WHO}

    who = who if who in dict(WHO) else None
    shown = rows if who is None else [r for r in rows
                                      if _is_his(r) == (who == "mine")]

    grouped = {state: [r for r in shown if (r["state"] or "open") == state]
               for state in STATES}
    grouped["total"] = len(shown)
    grouped["all_total"] = len(rows)
    grouped["tally"] = tally
    grouped["who"] = who
    # Without a name set, "mine" cannot mean anything and the filter says so
    # rather than quietly showing him everything.
    grouped["knows_him"] = bool(config.OWNER_NAME)
    return grouped


def set_state(action_id: int, state: str, note: str | None = None) -> dict:
    """Move one action. done_at is kept in step because other queries read it."""
    if state not in STATES:
        raise ValueError(f"{state!r} is not one of {', '.join(STATES)}")
    with cursor() as conn:
        conn.execute(
            "UPDATE action_items SET state = ?, state_at = datetime('now'), "
            "state_note = ?, done_at = CASE WHEN ? = 'done' THEN datetime('now') "
            "ELSE NULL END WHERE id = ?",
            (state, (note or "").strip() or None, state, action_id))
        row = conn.execute(
            "SELECT state, state_at, state_note FROM action_items WHERE id = ?",
            (action_id,)).fetchone()
    return dict(row) if row else {}


def counts() -> dict:
    with cursor() as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) AS n FROM action_items GROUP BY state").fetchall()
    out = {state: 0 for state in STATES}
    for row in rows:
        out[row["state"] or "open"] = row["n"]
    return out


def open_count() -> int:
    with cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM action_items WHERE state = 'open'").fetchone()
    return row["n"] if row else 0
