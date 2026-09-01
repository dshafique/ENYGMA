"""A meeting that arrived as notes rather than audio.

Somebody else's minutes, or a meeting tool's own summary, are a record of
something that happened and belong in Meetings. What they are not is checkable:
there is no recording behind them, so nothing can point at the moment it was
said. Everything here keeps that distinction visible rather than quietly letting
notes look like a transcript.

Text extraction is the Library's, because a file is a file.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..db import cursor
from ..library import Rejected, extract

# Anything the Library can read as text can be a set of notes.
SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".html", ".htm", ".pdf",
            ".json", ".csv", ".log"}


def is_notes(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUFFIXES


def _title_from(filename: str, text: str) -> str:
    """The first heading if there is one, otherwise the file name."""
    for line in text.splitlines()[:12]:
        line = line.strip().lstrip("#").strip()
        # A title is short, has words, and is not a date or a label.
        if 3 < len(line) < 90 and not line.endswith(":") \
                and not re.fullmatch(r"[\d\s/.:-]+", line) \
                and line.lower() not in ("summary", "notes", "attendees", "invited"):
            return line
    stem = re.sub(r"[_\-]+", " ", Path(filename).stem).strip()
    return stem or "Untitled notes"


def store(filename: str, raw: bytes) -> dict:
    """Text in, a queued meeting out. Content addressed like everything else."""
    filename = Path(filename.replace("\\", "/")).name
    text = extract(filename, raw)              # raises Rejected, with a sentence
    if len(text.split()) < 20:
        raise Rejected("There is not enough in that to be a meeting. "
                       "If it is reference material, put it in the Library.")

    digest = hashlib.sha256(raw).hexdigest()
    with cursor() as conn:
        existing = conn.execute(
            "SELECT id, title FROM recordings WHERE sha256 = ?", (digest,)).fetchone()
        if existing:
            return {"id": existing["id"], "title": existing["title"],
                    "duplicate": True, "kind": "notes"}

        title = _title_from(filename, text)
        conn.execute(
            "INSERT INTO recordings (title, source, original_filename, mime, "
            " sha256, bytes, status, source_text) "
            "VALUES (?, 'notes', ?, 'text/plain', ?, ?, 'queued', ?)",
            (title, filename, digest, len(raw), text))
        recording_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return {"id": recording_id, "title": title, "duplicate": False,
            "kind": "notes", "words": len(text.split())}


def paragraphs(text: str) -> list[str]:
    """The notes, split into readable blocks.

    These become the segments so the reader, the search and the hold-a-word
    popover all work the same way they do for a transcript. They carry no
    timestamps, because there are none to carry.
    """
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    out: list[str] = []
    for block in blocks:
        # A very long block is hard to read and useless to point at.
        words = block.split()
        if len(words) <= 160:
            out.append(" ".join(block.split("\n")).strip())
            continue
        for i in range(0, len(words), 140):
            out.append(" ".join(words[i:i + 140]))
    return out
