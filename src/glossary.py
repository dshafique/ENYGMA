"""The glossary behind the hold-a-word popover.

A lookup that misses is not a failure. The popover says so plainly and offers to
ask, because "ENYGMA does not know this yet" is more useful than a confident
paragraph about the wrong thing.
"""
import re

from .db import cursor

# Seeded so the popover is useful on day one. Everything here is a plain
# definition; nothing is inferred about him from it.
SEED = [
    ("MQTT", "protocol",
     "A lightweight publish and subscribe messaging protocol built for devices on "
     "unreliable networks. Clients publish to a topic on a broker and other clients "
     "subscribe to it, so neither side needs to know the other exists."),
    ("Node-RED", "tool",
     "A browser-based flow editor for wiring together devices, APIs and services. "
     "You drag nodes onto a canvas and connect them, and the flow runs on Node.js."),
    ("Broker", "concept",
     "The server in a publish and subscribe system. It receives every published "
     "message and forwards it to whoever subscribed to that topic."),
    ("Retained message", "concept",
     "In MQTT, a message the broker keeps as the last known value for a topic, so a "
     "client that subscribes later receives it immediately instead of waiting."),
    ("Diarization", "method",
     "Working out who spoke when in an audio recording, and splitting it into turns "
     "attributed to distinct speakers. Separate from transcribing the words."),
    ("Change request", "method",
     "A formal note that work now differs from what was agreed, so scope, cost or "
     "date can be renegotiated rather than absorbed quietly."),
    ("Quality of Service", "concept",
     "In MQTT, the delivery guarantee attached to a message: at most once, at least "
     "once, or exactly once. Higher levels cost more round trips."),
    ("Firmware", "concept",
     "Software written into a device to run its hardware directly, updated far less "
     "often than an application and often needing physical access to recover."),
]


def slugify(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (term or "").strip().lower()).strip("-")


def seed_if_empty() -> int:
    with cursor() as conn:
        if conn.execute("SELECT COUNT(*) AS n FROM terms").fetchone()["n"]:
            return 0
        conn.executemany(
            "INSERT OR IGNORE INTO terms (term, slug, gloss, kind) VALUES (?, ?, ?, ?)",
            [(t, slugify(t), g, k) for t, k, g in SEED],
        )
    return len(SEED)


def peek(term: str) -> dict | None:
    """Look without counting. Used while guessing which words are the term."""
    slug = slugify(term)
    if not slug:
        return None
    with cursor() as conn:
        row = conn.execute("SELECT * FROM terms WHERE slug = ?", (slug,)).fetchone()
    return dict(row) if row else None


def lookup(term: str) -> dict | None:
    slug = slugify(term)
    if not slug:
        return None
    with cursor() as conn:
        row = conn.execute("SELECT * FROM terms WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE terms SET asked_count = asked_count + 1 WHERE id = ?",
                     (row["id"],))
    return dict(row)


def listing() -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM terms ORDER BY asked_count DESC, term")]
