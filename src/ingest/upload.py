"""Drag and drop ingest.

Content addressed: the same file dropped twice is one recording, whatever it was
called the second time. That is the only dedupe rule, and it is exact — no fuzzy
matching on titles, no guessing that two files are "probably" the same meeting.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..config import config, BASE_DIR
from ..db import cursor

UPLOADS = BASE_DIR / "uploads"
CHUNK = 1024 * 1024


class Rejected(ValueError):
    """The file will never be accepted. Says why, in a sentence."""


def _title_from(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    # A leading timestamp from a recorder is noise, not a title.
    stem = re.sub(r"^\d{4}[-_ ]?\d{2}[-_ ]?\d{2}[ T]*\d{0,6}\s*", "", stem).strip()
    return stem or "Untitled recording"


def check(filename: str, size_bytes: int | None = None) -> str:
    """Validate before a byte is written. Returns the mime type."""
    suffix = Path(filename).suffix.lower()
    if suffix not in config.ALLOWED_AUDIO:
        allowed = ", ".join(sorted(config.ALLOWED_AUDIO))
        raise Rejected(f"{suffix or 'That file'} is not audio ENYGMA can read. Try {allowed}.")
    if size_bytes is not None and size_bytes > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise Rejected(f"That file is over the {config.MAX_UPLOAD_MB} MB limit.")
    return config.ALLOWED_AUDIO[suffix]


def store(filename: str, stream) -> dict:
    """Write the stream to disk, hashing as it goes.

    Returns {'id', 'title', 'duplicate', 'bytes'}. Hashing during the write rather
    than after means a 400 MB file is read once, not twice.
    """
    # A browser sends the full client path on some platforms; keep the leaf only.
    filename = Path(filename.replace("\\", "/")).name
    mime = check(filename)
    suffix = Path(filename).suffix.lower()
    UPLOADS.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    tmp = UPLOADS / f".incoming-{id(stream):x}{suffix}"
    total = 0
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise Rejected(f"That file is over the {config.MAX_UPLOAD_MB} MB limit.")
                digest.update(chunk)
                out.write(chunk)
        if total == 0:
            raise Rejected("That file is empty.")
        sha = digest.hexdigest()

        with cursor() as conn:
            existing = conn.execute(
                "SELECT id, title FROM recordings WHERE sha256 = ?", (sha,)
            ).fetchone()
        if existing:
            tmp.unlink(missing_ok=True)
            return {"id": existing["id"], "title": existing["title"],
                    "duplicate": True, "bytes": total}

        final = UPLOADS / f"{sha[:16]}{suffix}"
        tmp.replace(final)
        title = _title_from(filename)
        with cursor() as conn:
            conn.execute(
                "INSERT INTO recordings "
                "(title, audio_path, bytes, sha256, source, original_filename, mime, status) "
                "VALUES (?, ?, ?, ?, 'upload', ?, ?, 'queued')",
                (title, final.relative_to(BASE_DIR).as_posix(), total, sha, filename, mime),
            )
            row = conn.execute("SELECT id FROM recordings WHERE sha256 = ?", (sha,)).fetchone()
        return {"id": row["id"], "title": title, "duplicate": False, "bytes": total}
    finally:
        tmp.unlink(missing_ok=True)
