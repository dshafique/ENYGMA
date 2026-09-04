"""The bench: the two surfaces where what is stored is simply what he typed.

Everything else in ENYGMA is derived. Meetings come from audio, actions come
from meetings, the week's note comes from both. These do not, which is why they
share a tab and why they are the plainest code in the project.

The backlog has two states rather than four. There are two people and one of
them is maintenance, so "open" and "crossed off" is the whole vocabulary. What
makes two states survivable is the note: when something is crossed off, one line
saying why is the difference between "he fixed it" and "he decided against it",
and six weeks later neither of them will remember which.
"""
from __future__ import annotations

from .db import cursor

KINDS = ("bug", "idea", "todo")
KIND_LABELS = {"bug": "Bug", "idea": "Idea", "todo": "To do"}


# ---------------------------------------------------------------- backlog

def add(text: str, kind: str = "bug") -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("There is nothing to add.")
    kind = kind if kind in KINDS else "bug"
    with cursor() as conn:
        conn.execute("INSERT INTO bench_entries (kind, text) VALUES (?, ?)",
                     (kind, text[:2000]))
        return entry(conn.execute(
            "SELECT last_insert_rowid() AS i").fetchone()["i"])


def entry(entry_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM bench_entries WHERE id = ?",
                           (entry_id,)).fetchone()
    return dict(row) if row else None


def cross_off(entry_id: int, done: bool = True, note: str | None = None) -> dict | None:
    """Crossing off keeps done_at in step, and putting something back clears
    both it and the note, so a reopened entry does not carry the reason it was
    closed the first time."""
    with cursor() as conn:
        conn.execute(
            "UPDATE bench_entries SET done = ?, "
            "  done_at = CASE WHEN ? THEN datetime('now') ELSE NULL END, "
            "  note = CASE WHEN ? THEN ? ELSE NULL END "
            "WHERE id = ?",
            (1 if done else 0, done, done, (note or "").strip() or None, entry_id))
    return entry(entry_id)


def listing() -> dict:
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bench_entries ORDER BY done, id DESC")]
    return {"open": [r for r in rows if not r["done"]],
            "done": [r for r in rows if r["done"]],
            "total": len(rows)}


def counts() -> dict:
    with cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, SUM(done = 0) AS open FROM bench_entries"
        ).fetchone()
    return {"total": row["total"] or 0, "open": row["open"] or 0}


# ------------------------------------------------------------------ notes

def new_note() -> dict:
    with cursor() as conn:
        conn.execute("INSERT INTO bench_notes (title, body) VALUES ('Untitled', '')")
        return note(conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"])


def note(note_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM bench_notes WHERE id = ?",
                           (note_id,)).fetchone()
    return dict(row) if row else None


def save_note(note_id: int, title: str | None = None,
              body: str | None = None) -> dict | None:
    """The title comes from the first line when he has not set one himself, so a
    note he simply started typing into still has a name in the list."""
    current = note(note_id)
    if current is None:
        return None
    body = current["body"] if body is None else body
    if title is None or not title.strip():
        first = next((line.strip() for line in (body or "").splitlines()
                      if line.strip()), "")
        title = first[:80] or "Untitled"
    with cursor() as conn:
        conn.execute("UPDATE bench_notes SET title = ?, body = ?, "
                     "updated_at = datetime('now') WHERE id = ?",
                     (title.strip()[:120], body, note_id))
    return note(note_id)


def pin(note_id: int, pinned: bool = True) -> dict | None:
    with cursor() as conn:
        conn.execute("UPDATE bench_notes SET pinned = ? WHERE id = ?",
                     (1 if pinned else 0, note_id))
    return note(note_id)


def remove_note(note_id: int) -> bool:
    with cursor() as conn:
        conn.execute("DELETE FROM bench_notes WHERE id = ?", (note_id,))
        return conn.execute("SELECT changes() AS n").fetchone()["n"] > 0


def notes() -> list[dict]:
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM bench_notes ORDER BY pinned DESC, updated_at DESC, id DESC")]
    for row in rows:
        row["preview"] = _preview(row["body"], row["title"])
    return rows


def _preview(body: str, title: str) -> str:
    """The first line that is not the title, so the list is not every note
    repeating its own name."""
    for line in (body or "").splitlines():
        line = line.strip()
        if line and line != title:
            return line[:90]
    return "Empty"
