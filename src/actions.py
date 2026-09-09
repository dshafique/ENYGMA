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
# The summariser writes this as the owner when the group took something on
# together. Distinct from an empty owner, which means nobody has picked it up --
# one is work that is owned and one is work that is going spare, and the whole
# suggestions surface rests on being able to tell them apart.
TEAM = "THE TEAM"
UNCLAIMED = "\u2014"          # the target key for "nobody's"


def target_of(row: dict) -> str:
    """Which target an action belongs to: a person's name, the team, or nobody.

    One function, because the filter, the counts and the chips must agree about
    this or the numbers stop matching the list.
    """
    owner = (row.get("owner_name") or row.get("owner") or "").strip()
    if not owner:
        return UNCLAIMED
    if owner.upper() == TEAM:
        return TEAM
    return owner


def targets() -> list[dict]:
    """Everyone who owns anything, plus the team and the unclaimed pile.

    Ordered with him first, because it is his list and his name is the one he
    looks for. Then people by how much they are carrying, then the two
    collective buckets, which are the ones he scans rather than searches.
    """
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute(_SELECT)]
    counted: dict[str, int] = {}
    for row in rows:
        key = target_of(row)
        counted[key] = counted.get(key, 0) + 1

    mine = config.OWNER_NAME
    people = [k for k in counted if k not in (TEAM, UNCLAIMED)
              and not (mine and k.casefold() == mine.casefold())]
    people.sort(key=lambda k: (-counted[k], k.casefold()))

    out = []
    if mine:
        match = next((k for k in counted if k.casefold() == mine.casefold()), mine)
        out.append({"key": match, "label": "Me", "count": counted.get(match, 0)})
    out += [{"key": k, "label": k, "count": counted[k]} for k in people]
    for key, label in ((TEAM, "The team"), (UNCLAIMED, "Unclaimed")):
        if counted.get(key):
            out.append({"key": key, "label": label, "count": counted[key]})
    return out


def listing(include_done: bool = True, who: list[str] | None = None) -> dict:
    """Every action, or only the ones belonging to the targets he picked.

    `who` is a list because he is usually asking a question about two of them at
    once -- his own work and the team's, or his own and whoever he is waiting on.
    Nothing picked means everything, which is the honest reading of an empty
    selection and saves him a Clear button.
    """
    where = "" if include_done else "WHERE a.state = 'open' "
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            _SELECT + where + "ORDER BY r.recorded_at DESC, a.id")]

    picked = [w for w in (who or []) if w]
    wanted = {w.casefold() for w in picked}
    shown = rows if not wanted else [
        r for r in rows if target_of(r).casefold() in wanted]

    grouped = {state: [r for r in shown if (r["state"] or "open") == state]
               for state in STATES}
    grouped["total"] = len(shown)
    grouped["all_total"] = len(rows)
    grouped["picked"] = picked
    # Counted across everything, always. A count that moves when you filter is
    # not a count, and that went wrong on the Bench once already.
    grouped["targets"] = targets()
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
