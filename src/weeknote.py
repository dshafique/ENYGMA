"""The Friday note.

Once a week ENYGMA writes the thing he would otherwise put off: three to five
bullets on what he got done, three to five on what he is doing next, in language
plain enough to paste into an email to his manager without editing.

Three rules run this file.

The first is that it must sound like a person. Not "leveraged a solution to
streamline the pipeline" -- "the export was slow, so I cut the query down and now
it takes four seconds". Feynman's register: say the thing, give the number, stop.
Rules in a prompt get ignored under pressure, so the ones that matter are
enforced here in code and the note is rewritten until it passes.

The second is that it must not invent. A quiet week produces a short note or no
note. It never produces a full one about work that did not happen, because the
first time it does, he stops trusting every note after it -- and he is sending
these to his manager.

The third is that next week must not promise on his behalf. A meeting discussing
something is not him agreeing to do it. Only what he took on himself gets in.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta

from . import voice
from .db import cursor
from .config import config

# What the model is told. Deliberately short: a long prompt full of prohibitions
# produces careful, stilted prose, which is the thing being avoided.
VOICE = """You are writing a short weekly update for an engineering intern to
send to his manager. Write it as him, in the first person.

How to write:
  * Plain words. If a shorter word works, use it.
  * Say what happened, give the number if there is one, then stop.
  * Short sentences. One idea each.
  * No selling. "Fixed the login bug" is finished; it does not need "successfully".
  * Explain the thing itself, the way you would to a friend who is not on the team.

Never use: leverage, utilise, delve, streamline, robust, seamless, spearhead,
facilitate, synergy, deep dive, circle back, align, holistic, impactful,
key learnings, excited to share, pleased to report, I had the opportunity to.
Never use an em dash or a semicolon.

Between three and five bullets per section. Each one a fact he could be asked
about. If there is not enough real material for three, write fewer."""

# The words, the typography and the shapes all live in src/voice.py now, so the
# Friday note and every generated document are held to one rule rather than two
# copies of it that drift. These names are kept because this module's callers
# and its tests read them.
BANNED = voice.BANNED
plain = voice.plain
offences = voice.offences


def clean(lines: list[str]) -> list[str]:
    """Plain typography, no empties, no numbering the template already provides."""
    out = []
    for line in lines or []:
        line = voice.tidy(str(line))
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line)
        if line:
            out.append(line[:400])
    return out[:5]


# ---------------------------------------------------------------- the week

def week_bounds(today: date | None = None) -> tuple[date, date]:
    """Monday to Friday of the week `today` falls in. Saturday and Sunday belong
    to the week that just ended, not the one about to start: a note written on
    Saturday is still about last week."""
    today = today or datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() >= 5:            # Saturday or Sunday
        pass                            # still this week's Monday; the week is over
    return monday, monday + timedelta(days=4)


def material(start: date, end: date) -> dict:
    """Everything ENYGMA holds for the week, and what is still owed after it.

    The window is inclusive of the whole Friday, so `end + 1 day` is the cutoff.
    """
    lo, hi = start.isoformat(), (end + timedelta(days=1)).isoformat()
    with cursor() as conn:
        meetings = [dict(r) for r in conn.execute(
            "SELECT r.id, r.title, r.recorded_at, s.abstract, s.decisions "
            "FROM recordings r LEFT JOIN summaries s ON s.recording_id = r.id "
            "WHERE r.status = 'ready' "
            "  AND COALESCE(r.recorded_at, r.created_at) >= ? "
            "  AND COALESCE(r.recorded_at, r.created_at) < ? "
            "ORDER BY COALESCE(r.recorded_at, r.created_at)", (lo, hi))]
        closed = [dict(r) for r in conn.execute(
            "SELECT a.id, a.text, r.title AS meeting FROM action_items a "
            "JOIN recordings r ON r.id = a.recording_id "
            "WHERE a.state = 'done' AND a.state_at >= ? AND a.state_at < ?",
            (lo, hi))]
        rejected = [dict(r) for r in conn.execute(
            "SELECT a.id, a.text, a.state_note FROM action_items a "
            "WHERE a.state = 'rejected' AND a.state_at >= ? AND a.state_at < ?",
            (lo, hi))]
        owed = [dict(r) for r in conn.execute(
            "SELECT a.id, a.text, a.state, r.title AS meeting FROM action_items a "
            "JOIN recordings r ON r.id = a.recording_id "
            "WHERE a.state IN ('open', 'pending') ORDER BY a.state, a.id")]
        docs = [dict(r) for r in conn.execute(
            "SELECT id, title FROM documents WHERE added_at >= ? AND added_at < ?",
            (lo, hi))]
        notes = [dict(r) for r in conn.execute(
            "SELECT id, title FROM recordings WHERE source_text IS NOT NULL "
            "  AND audio_path IS NULL AND created_at >= ? AND created_at < ?",
            (lo, hi))]
    return {"meetings": meetings, "closed": closed, "rejected": rejected,
            "owed": owed, "documents": docs, "notes": notes}


def is_empty(found: dict) -> bool:
    """Nothing happened that ENYGMA can see. Worth saying plainly."""
    return not (found["meetings"] or found["closed"] or found["rejected"]
                or found["documents"] or found["notes"])


def drawn_from(found: dict) -> str:
    """The provenance line, in words, so he can check before he sends."""
    bits = []
    def count(n, one, many):
        if n:
            bits.append(f"{n} {one if n == 1 else many}")
    count(len(found["meetings"]), "meeting", "meetings")
    count(len(found["closed"]), "action you closed", "actions you closed")
    count(len(found["notes"]), "set of notes", "sets of notes")
    count(len(found["documents"]), "document", "documents")
    if not bits:
        return "nothing this week"
    if len(bits) == 1:
        return bits[0]
    return ", ".join(bits[:-1]) + " and " + bits[-1]


# ------------------------------------------------------------- the writing

NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "done": {"type": "array", "items": {"type": "string"}},
        "next": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["done", "next"],
}

EMPTY = {
    "done": [],
    "next": [],
    "empty": True,
}


def _brief(found: dict) -> str:
    """The week, as material for the model. Facts only, no instructions."""
    out = []
    if found["meetings"]:
        out.append("Meetings this week:")
        for m in found["meetings"]:
            line = f"  - {m['title']}"
            if m.get("abstract"):
                line += f": {m['abstract']}"
            out.append(line)
            for decision in json.loads(m.get("decisions") or "[]")[:4]:
                out.append(f"      decided: {decision}")
    if found["closed"]:
        out.append("\nHe finished these, and they are the strongest material:")
        out += [f"  - {a['text']}  (from {a['meeting']})" for a in found["closed"]]
    if found["notes"]:
        out.append("\nMeetings he has notes for but did not record:")
        out += [f"  - {n['title']}" for n in found["notes"]]
    if found["documents"]:
        out.append("\nHe added these to his library:")
        out += [f"  - {d['title']}" for d in found["documents"]]
    if found["rejected"]:
        out.append("\nHe turned these down on purpose. Do not list them as done:")
        out += [f"  - {a['text']}" for a in found["rejected"]]
    if found["owed"]:
        out.append("\nStill owed, for next week. Only include one if HE is the "
                   "person doing it:")
        out += [f"  - [{a['state']}] {a['text']}  (from {a['meeting']})"
                for a in found["owed"]]
    return "\n".join(out)


def compose(found: dict, backend=None) -> dict:
    """Write the note, then hold it to the rules whatever the model did.

    One retry, told exactly which words it used. Then, if it still will not
    behave, the offending bullets are dropped rather than sent: a shorter honest
    note is better than a long one that reads like a press release.
    """
    if is_empty(found):
        return dict(EMPTY, model=None)

    if config.PIPELINE != "gemini":
        return dict(_stub(found), model="stub")

    from .pipeline.gemini import GeminiBackend
    backend = backend or GeminiBackend()
    brief = _brief(found)

    ask = (f"{VOICE}\n\nHere is his week.\n\n{brief}\n\n"
           'Return JSON: {"done": [...], "next": [...]}')
    result, model = _try(backend, ask)

    bad = offences(result["done"] + result["next"])
    if bad:
        # Naming them is the difference between a retry that works and one that
        # makes the same mistake with more confidence.
        result, model = _try(backend, ask + (
            "\n\nYour last attempt used these words, which are banned: "
            + ", ".join(bad) + ". Write it again without them, in plainer words."))
        still = offences(result["done"] + result["next"])
        if still:
            result = {
                "done": [b for b in result["done"] if not offences([b])],
                "next": [b for b in result["next"] if not offences([b])],
            }
    return dict(result, model=model)


def _try(backend, ask: str) -> tuple[dict, str | None]:
    raw = backend._ask([{"type": "text", "text": ask}], schema=NOTE_SCHEMA)
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    return ({"done": clean(parsed.get("done") or []),
             "next": clean(parsed.get("next") or [])},
            getattr(backend, "model", None))


def _stub(found: dict) -> dict:
    """No model: the facts themselves, unwritten. Real, if plain."""
    done = [a["text"] for a in found["closed"]][:5]
    done += [f"Was in {m['title']}." for m in found["meetings"]][:5 - len(done)]
    return {"done": clean(done),
            "next": clean([a["text"] for a in found["owed"]][:5])}


# ------------------------------------------------------------------ storage

def _row_to_note(row) -> dict:
    """One row, ready for the template. His edit wins over what was generated."""
    generated = json.loads(row["body"] or "{}")
    edited = json.loads(row["edited"] or "null") if row["edited"] else None
    shown = edited or generated
    start = date.fromisoformat(row["week_start"])
    end = date.fromisoformat(row["week_end"])
    return {
        "id": row["id"],
        "done": shown.get("done") or [],
        "next": shown.get("next") or [],
        "empty": not (shown.get("done") or shown.get("next")),
        "edited": edited is not None,
        "drawn_from": row["drawn_from"] or "nothing this week",
        "range": f"{start.strftime('%a %-d %b')} – {end.strftime('%a %-d %b')}".upper(),
        "week_start": row["week_start"],
        "generated_at": row["generated_at"],
    }


def stored(week_start: date) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM week_notes WHERE week_start = ?",
                           (week_start.isoformat(),)).fetchone()
    return _row_to_note(row) if row else None


def stored_exists(week_start: str) -> bool:
    with cursor() as conn:
        return conn.execute("SELECT 1 FROM week_notes WHERE week_start = ?",
                            (week_start,)).fetchone() is not None


def latest() -> dict | None:
    with cursor() as conn:
        row = conn.execute(
            "SELECT * FROM week_notes ORDER BY week_start DESC LIMIT 1").fetchone()
    return _row_to_note(row) if row else None


def write(week_start: date | None = None, backend=None, keep_edit: bool = False) -> dict:
    """Generate and store one week. Re-running replaces what was generated.

    keep_edit is False for a deliberate re-roll -- he asked for a new one, so his
    old edit is what he is replacing. It is True for the automatic Friday write,
    which must never quietly overwrite something he has already fixed by hand.
    """
    start, end = week_bounds(week_start)
    found = material(start, end)
    written = compose(found, backend=backend)
    body = json.dumps({"done": written["done"], "next": written["next"]})
    sources = json.dumps({
        "meetings": [m["id"] for m in found["meetings"]],
        "actions": [a["id"] for a in found["closed"]],
        "documents": [d["id"] for d in found["documents"]],
    })
    with cursor() as conn:
        conn.execute(
            "INSERT INTO week_notes "
            "  (week_start, week_end, body, drawn_from, sources, model) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(week_start) DO UPDATE SET "
            "  body = excluded.body, drawn_from = excluded.drawn_from, "
            "  sources = excluded.sources, model = excluded.model, "
            "  generated_at = datetime('now'), "
            + ("edited = week_notes.edited" if keep_edit else
               "edited = NULL, edited_at = NULL"),
            (start.isoformat(), end.isoformat(), body,
             drawn_from(found), sources, written.get("model")))
    return stored(start)


def save_edit(week_start: str, done: list[str], next_week: list[str]) -> dict:
    """His version. Stored beside the generated one, never on top of it, so
    'write it again' is always available and never destroys his work silently."""
    payload = json.dumps({"done": clean(done), "next": clean(next_week)})
    with cursor() as conn:
        conn.execute(
            "UPDATE week_notes SET edited = ?, edited_at = datetime('now') "
            "WHERE week_start = ?", (payload, week_start))
    return stored(date.fromisoformat(week_start))


def as_email(note: dict) -> str:
    """What the Copy button puts on his clipboard. Plain text, no markdown: it is
    going into an email body, where asterisks would show up as asterisks."""
    out = []
    if note["done"]:
        out.append("What I got done this week")
        out += [f"- {line}" for line in note["done"]]
    if note["next"]:
        if out:
            out.append("")
        out.append("What I am working on next week")
        out += [f"- {line}" for line in note["next"]]
    return "\n".join(out)


# ------------------------------------------------------------------ Friday

def due(now: datetime | None = None) -> date | None:
    """The Monday of a week that should have a note by now and does not.

    Friday afternoon is the trigger, but the machine might have been asleep then,
    or he might not open the app until Sunday night. So this asks a question with
    no clock in it: is there a finished week without a note? A missed Friday
    turns into a note waiting for him, not a week that never got written.
    """
    now = now or datetime.now()
    start, _ = week_bounds(now.date())
    ready = now.weekday() > 4 or (now.weekday() == 4 and now.hour >= config.WEEKNOTE_HOUR)
    candidates = [start - timedelta(days=7)]
    if ready:
        candidates.append(start)
    with cursor() as conn:
        for monday in sorted(candidates):
            row = conn.execute("SELECT 1 FROM week_notes WHERE week_start = ?",
                               (monday.isoformat(),)).fetchone()
            if row is None:
                # Nothing to say about a week with nothing in it. Checking here
                # rather than writing an empty row keeps a quiet first week from
                # looking like a broken feature.
                found = material(monday, monday + timedelta(days=4))
                if not is_empty(found):
                    return monday
    return None


def write_if_due(now: datetime | None = None, backend=None) -> dict | None:
    monday = due(now)
    return write(monday, backend=backend, keep_edit=True) if monday else None
