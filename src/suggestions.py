"""Work nobody has picked up.

Every action item in ENYGMA came from a person saying they would do a thing.
This is the other half: what a meeting left on the floor. A question raised and
never answered. Something his manager asked for twice and nobody wrote down. A
gap sitting between two people's work that each assumed the other had.

The thing this feature has to not become is career-advice slop -- "take
ownership of cross-functional alignment" -- which is worse than useless, because
acting on it would embarrass him in front of the people he is trying to impress.
Two rules keep it honest, and both are enforced here rather than asked for in a
prompt:

    Nothing without a citation. A suggestion that cannot point at a meeting and
    a moment does not get stored. He has to be able to go and listen.

    Nothing that somebody owns. If a person or the team has it, it is not going
    spare, and offering it would be telling him to tread on a colleague.

And the structural one, which is why this table is not action_items: a
suggestion has no state he can tick, appears on no other surface, and is in no
count. It becomes real only by being taken, and taking it writes an ordinary
action item with his name on it. From that moment it is a commitment and looks
like one, because it is one.
"""
from __future__ import annotations

from .db import cursor

# What the model is asked for. Deliberately not "how can he stand out": that
# question invites invention, and what he actually wants is the narrower and
# more useful one -- what did this meeting drop.
FIND_PROMPT = """Here are recent meeting summaries and the transcript moments
around them, plus everything anybody committed to.

Find work the meetings LEFT ON THE FLOOR. Not work that was assigned. Not work
somebody is already doing. The gaps: a question raised and never answered, a
thing asked for twice with no reply, a piece sitting between two people's jobs
that each assumed the other had, a decision that was deferred and never came
back.

Return JSON only:
{"gaps":[{"gap":"...","why":"...","could":"...","meeting_id":123,"at":"MM:SS"}]}

For each one:
- "gap" is the subject, in under ten words, as a noun phrase and not a sentence.
  "What happens to camera images after a week". "How design decisions get
  recorded". It is read on its own before he decides to read any further, so it
  must name the thing without arguing for it.
- "why" is the evidence, in one or two sentences: what happened in the meeting
  that shows nobody is holding this. "Joseph and Jacob both hit it looking at
  the MyCodo API and both moved on." "Luigi asked twice and neither time did
  anyone answer."
- "could" is the move he could make, phrased as something he could do and never
  as an instruction. It will be shown to him as "You could ...". Keep it small
  and concrete enough to start this week.
- "meeting_id" and "at" point at where the gap is visible. If you cannot point
  at a real moment in a real meeting, do not include the item at all. This is
  the one place where dropping is right: an uncited suggestion is a rumour.

Rules:
- Never suggest something that already has an owner. Check the commitments list.
- Never invent a gap to have something to say. Two real ones beat eight plausible
  ones, and an empty list is a perfectly good answer to a well run meeting.
- No advice about how he should behave, present himself, or be perceived. Only
  work that is genuinely unheld.
- At most five.

MATERIAL:
"""


def _rows(state: str | None = None) -> list[dict]:
    where = "WHERE s.state = ? " if state else ""
    args = (state,) if state else ()
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT s.*, r.title AS meeting FROM suggestions s "
            "LEFT JOIN recordings r ON r.id = s.recording_id "
            + where + "ORDER BY s.created_at DESC, s.id DESC", args)]


def offered() -> list[dict]:
    """What is on the table. Passed and taken ones are not shown again."""
    return _rows("offered")


def count() -> int:
    with cursor() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM suggestions WHERE state = 'offered'"
        ).fetchone()["n"]


def take(suggestion_id: int) -> dict | None:
    """He wants it. It stops being a suggestion and becomes his action item.

    The suggestion is not deleted, so pressing this twice cannot make two
    commitments out of one guess, and the Bench keeps a record of where the item
    came from.
    """
    from .config import config
    with cursor() as conn:
        row = conn.execute("SELECT * FROM suggestions WHERE id = ?",
                           (suggestion_id,)).fetchone()
        if row is None or row["state"] != "offered":
            return None
        conn.execute(
            "INSERT INTO action_items (recording_id, text, owner, at_ms) "
            "VALUES (?, ?, ?, ?)",
            (row["recording_id"], row["could"], config.OWNER_NAME or None,
             row["at_ms"]))
        action_id = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        conn.execute(
            "UPDATE suggestions SET state = 'taken', state_at = datetime('now'), "
            "action_id = ? WHERE id = ?", (action_id, suggestion_id))
    return {"id": suggestion_id, "action_id": action_id}


def pass_on(suggestion_id: int) -> bool:
    """Not for him. Kept rather than deleted, so the next look does not offer
    the same thing back and make the surface feel like it is not listening."""
    with cursor() as conn:
        changed = conn.execute(
            "UPDATE suggestions SET state = 'passed', state_at = datetime('now') "
            "WHERE id = ? AND state = 'offered'", (suggestion_id,)).rowcount
    return bool(changed)


def _material(limit: int = 6) -> tuple[str, set[int]]:
    """Recent meetings and every commitment made in them.

    The commitments go in so the model can tell what is already held. Without
    them it would offer him work Joseph is in the middle of, which is worse than
    offering nothing.
    """
    with cursor() as conn:
        meetings = [dict(r) for r in conn.execute(
            "SELECT r.id, r.title, r.recorded_at, s.abstract, s.topics, s.questions "
            "FROM recordings r JOIN summaries s ON s.recording_id = r.id "
            "WHERE r.status = 'ready' "
            # id breaks the tie. Several meetings on one day is normal and
            # without it "the last six" is undefined, so a meeting recorded an
            # hour ago could be left out in favour of one from the morning.
            "ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.id DESC "
            "LIMIT ?", (limit,))]
        ids = [m["id"] for m in meetings]
        held = []
        if ids:
            marks = ",".join("?" * len(ids))
            held = [dict(r) for r in conn.execute(
                "SELECT a.recording_id, a.text, a.owner, "
                "  (SELECT p.person_name FROM speakers p "
                "   WHERE p.recording_id = a.recording_id AND p.label = a.owner) "
                "   AS owner_name "
                f"FROM action_items a WHERE a.recording_id IN ({marks})", ids)]
        # Already offered, so a second look does not repeat itself.
        seen = [r["gap"] for r in conn.execute(
            "SELECT gap FROM suggestions")]

    import json
    out = []
    for m in meetings:
        out.append(f"\n=== MEETING {m['id']}: {m['title']} ({m['recorded_at'] or ''})")
        if m["abstract"]:
            out.append(m["abstract"])
        for t in json.loads(m["topics"] or "[]"):
            out.append(f"  - {t.get('heading')}: {t.get('text')}")
        for q in json.loads(m["questions"] or "[]"):
            at = q.get("at_ms")
            out.append(f"  OPEN QUESTION{f' at {at // 1000 // 60}:{at // 1000 % 60:02d}' if at else ''}: {q.get('text')}")
    if held:
        out.append("\n=== ALREADY OWNED, DO NOT SUGGEST ANY OF THESE")
        for a in held:
            who = a["owner_name"] or a["owner"] or "nobody"
            out.append(f"  - [{who}] {a['text']}")
    if seen:
        out.append("\n=== ALREADY OFFERED BEFORE, DO NOT REPEAT")
        out += [f"  - {g}" for g in seen]
    return "\n".join(out), set(ids)


FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "gap": {"type": "string"},
                    "why": {"type": "string"},
                    "could": {"type": "string"},
                    "meeting_id": {"type": "integer"},
                    "at": {"type": "string"},
                },
                "required": ["gap", "why", "could", "meeting_id"],
            },
        },
    },
    "required": ["gaps"],
}


def look(backend=None) -> dict:
    """Read the recent meetings and write down what nobody is holding.

    Deliberately on demand. A background job that quietly spends money to
    produce guesses is the wrong shape for this: he should press a thing and get
    an answer, and see nothing the rest of the time.
    """
    import json
    from .config import config
    from .pipeline.gemini import _ms

    material, known = _material()
    if not known:
        return {"found": 0, "why": "There are no meetings to read yet."}

    if backend is None:
        from . import models
        backend = models.backend_for(None)

    raw = backend._ask([{"type": "text", "text": FIND_PROMPT + material}],
                       schema=FIND_SCHEMA)
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        payload = {}

    kept = 0
    with cursor() as conn:
        for row in payload.get("gaps") or []:
            gap = (row.get("gap") or "").strip()
            why = (row.get("why") or "").strip()
            could = (row.get("could") or "").strip()
            meeting = row.get("meeting_id")
            # The citation rule, enforced here rather than trusted to the model.
            # An uncited suggestion is a rumour, and a suggestion pointing at a
            # meeting that was not in the material is an invented one.
            if not (gap and why and could and meeting in known):
                continue
            conn.execute(
                "INSERT INTO suggestions (gap, why, could, recording_id, at_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (gap[:200], why[:400], could[:400], meeting, _ms(row.get("at"))))
            kept += 1
    return {"found": kept, "model": getattr(backend, "model", "")}
