"""What he brings to a conversation.

Two kinds, handled differently on purpose.

An image goes to the model. He is standing at a bench with a board in front of
him and a question about it, and a photograph is the fastest way to ask. Every
model ENYGMA can reach has vision, including the local one, so this works
without anything leaving the building.

Everything else is read for its text and pushed into the Library, where search
already reaches it. A datasheet is not something to look at once; it is
something to be able to quote in three weeks.

Both are kept and downloadable either way, because a file he attached and cannot
get back is worse than one he never attached.
"""
from __future__ import annotations

import hashlib
import pathlib

from . import config as _config
from . import library
from .db import cursor

BASE_DIR = _config.BASE_DIR
DATA_DIR = _config.DATA_DIR
ATTACHED = DATA_DIR / "attached"

# What a model will actually look at. Everything else is read as text.
IMAGE_MIMES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp",
}
# Deliberately absent: .heic. Samsung shoots JPEG, but an iPhone does not, and
# no model here reads HEIC. Refusing it with a sentence beats accepting it and
# answering about an image nobody could see.
REFUSED = {".heic", ".heif"}

TEXT_MIMES = {
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
    ".csv": "text/csv", ".json": "application/json", ".log": "text/plain",
    ".html": "text/html", ".htm": "text/html", ".rst": "text/plain",
}

MAX_BYTES = 25 * 1024 * 1024


class Refused(ValueError):
    """Will never be accepted. Says why, in a sentence."""


def check(filename: str) -> tuple[str, str]:
    """(kind, mime), or a refusal that explains itself."""
    suffix = pathlib.Path(filename or "").suffix.lower()
    if suffix in REFUSED:
        raise Refused(
            f"{suffix} images cannot be read by any of the models. Share it as "
            "a JPEG or a PNG and it will work.")
    if suffix in IMAGE_MIMES:
        return "image", IMAGE_MIMES[suffix]
    if suffix in TEXT_MIMES:
        return "file", TEXT_MIMES[suffix]
    raise Refused(f"{suffix or 'That'} is not something ENYGMA can read. "
                  "Images, PDFs and text files work.")


def _store(data: bytes, suffix: str) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    ATTACHED.mkdir(parents=True, exist_ok=True)
    ATTACHED.chmod(0o700)
    path = ATTACHED / f"{digest[:32]}{suffix}"
    if not path.exists():
        path.write_bytes(data)
        path.chmod(0o600)
    return str(path.relative_to(DATA_DIR)), digest


def attach(thread_id: int, filename: str, data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise Refused(f"That is {len(data) / 1024 / 1024:.0f} MB. "
                      f"The limit is {MAX_BYTES // 1024 // 1024} MB.")
    if not data:
        raise Refused("That file is empty.")
    kind, mime = check(filename)
    suffix = pathlib.Path(filename).suffix.lower()
    path, digest = _store(data, suffix)

    extracted, library_id = None, None
    if kind == "file":
        # Read once, here, so the model never has to be handed a PDF and the
        # Library has it whether or not this conversation goes anywhere.
        extracted = library.extract(filename, data)
        try:
            entry = library.add(pathlib.Path(filename).stem, extracted, kind="file",
                                source_name=filename, mime=mime, raw=data,
                                note="Attached in Chat.")
            library_id = entry.get("id")
        except Exception:
            library_id = None            # the Library is a convenience

    with cursor() as conn:
        conn.execute(
            "INSERT INTO attachments (thread_id, filename, mime, kind, path, "
            "  bytes, sha256, extracted, library_document_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (thread_id, filename[:200], mime, kind, path, len(data), digest,
             (extracted or "")[:20000] or None, library_id))
        return get(conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"])


def get(attachment_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id = ?",
                           (attachment_id,)).fetchone()
    return dict(row) if row else None


def pending(thread_id: int) -> list[dict]:
    """Attached but not yet sent with a message. These are what the next
    question carries."""
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM attachments WHERE thread_id = ? AND message_id IS NULL "
            "ORDER BY id", (thread_id,))]


def claim(thread_id: int, message_id: int) -> list[dict]:
    """Tie everything waiting to the message that has just been sent."""
    waiting = pending(thread_id)
    if waiting:
        with cursor() as conn:
            conn.execute("UPDATE attachments SET message_id = ? "
                         "WHERE thread_id = ? AND message_id IS NULL",
                         (message_id, thread_id))
    return waiting


def for_message(message_id: int) -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, filename, mime, kind, bytes FROM attachments "
            "WHERE message_id = ? ORDER BY id", (message_id,))]


def blob(attachment_id: int) -> tuple[pathlib.Path, dict] | None:
    row = get(attachment_id)
    if row is None:
        return None
    for root in (DATA_DIR, BASE_DIR):
        path = pathlib.Path(root) / row["path"]
        if path.exists():
            return path, row
    return None


def parts_for(rows: list[dict]) -> tuple[list[dict], str]:
    """What goes to the model, and what goes in the prompt as words.

    Images become image parts. Documents were already read at attach time, so
    they arrive as text rather than as a file the model has to be taught to
    open.
    """
    parts, said = [], []
    for row in rows:
        if row["kind"] == "image":
            found = blob(row["id"])
            if found:
                parts.append({"type": "image", "mime": row["mime"],
                              "data": found[0].read_bytes()})
                said.append(f"an image, {row['filename']}")
        elif row.get("extracted"):
            parts.append({"type": "text",
                          "text": f"From the file he attached, {row['filename']}:\n\n"
                                  + row["extracted"][:12000]})
            said.append(f"a file, {row['filename']}")
    return parts, ", ".join(said)


def readable(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
