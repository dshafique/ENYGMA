"""Storing the files ENYGMA makes, and putting them where he will find them.

Two places, because they answer two different questions. The file goes in the
conversation, where he asked for it and where he will look for it. Its prose
goes in the Library, so a question next month can quote a document made today
without him having to remember he made it.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from . import documents, library
from . import config as _config
from .db import cursor

# Under data/, not beside it.
#
# The service runs with ProtectSystem=strict and ProtectHome=read-only, and
# deploy/enygma.service lists exactly two writable paths: app/data and
# app/uploads. A sibling directory is read-only at the kernel level however the
# file permissions look, which is how the first version of this shipped and then
# failed on the Spark with "[Errno 30] Read-only file system" the moment he
# asked for a file. Living under data/ also means the nightly backup already
# carries these, and the isolation check already covers them.
#
# Module level and read at call time, the same way src/ingest/upload.py does it,
# so a test can move the store without the stored paths and the directory
# disagreeing about where the root is.
BASE_DIR = _config.BASE_DIR
DATA_DIR = _config.DATA_DIR
MADE = DATA_DIR / "made"


def _store(data: bytes, fmt: str) -> tuple[str, str]:
    """Content addressed. The same document twice is one file on disk."""
    digest = hashlib.sha256(data).hexdigest()
    MADE.mkdir(parents=True, exist_ok=True)
    MADE.chmod(0o700)
    path = MADE / f"{digest[:32]}.{fmt}"
    if not path.exists():
        path.write_bytes(data)
        path.chmod(0o600)
    # Relative to the data directory, not to the application root. They are the
    # same place today, because data/ sits inside app/, but the moment anyone
    # points ENYGMA_DATA at another disk -- which is exactly what you do when the
    # Spark's disk fills -- relative_to(BASE_DIR) raises and every document fails
    # to save with a path error that reads like a bug in the renderer.
    return str(path.relative_to(DATA_DIR)), digest


def create(brief: str, fmt: str, *, context: str = "", thread_id: int | None = None,
           style: str = "plain", backend=None, to_library: bool = True,
           fallback_title: str = "") -> dict:
    """Make one document, keep it, and hand back the row."""
    if fmt not in documents.FORMATS:
        raise ValueError(f"{fmt!r} is not a format ENYGMA can write.")
    from . import spend
    from .pipeline.gemini import GeminiBackend
    backend = backend or GeminiBackend()
    doc = documents.compose(brief, context, backend=backend,
                            fallback_title=fallback_title)
    # Billed here rather than inside compose, because compose can call twice
    # when the voice rules send it back and the caller should pay for both.
    usage = getattr(backend, "usage", None) or {}
    if usage.get("input") or usage.get("output"):
        provider = "anthropic" if getattr(backend, "name", "") == "opus" else "google"
        spend.record(provider, getattr(backend, "model", "?"), "document",
                     usage.get("input", 0), usage.get("output", 0),
                     thread_id=thread_id)
    data = documents.render(doc, fmt, style)
    name = documents.filename(doc, fmt)
    path, digest = _store(data, fmt)

    library_id = None
    if to_library:
        try:
            entry = library.add(
                doc["title"], documents.as_text(doc), kind="file",
                source_name=name, mime=documents.MIMES[fmt],
                note=f"Made by ENYGMA as a {documents.NAMES[fmt].lower()}.")
            library_id = entry.get("id")
        except Exception:
            # The Library is a convenience. Losing it must never lose the file
            # he actually asked for.
            library_id = None

    with cursor() as conn:
        conn.execute(
            "INSERT INTO made_documents (thread_id, format, style, title, filename, "
            "  mime, path, bytes, sha256, brief, structure, library_document_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (thread_id, fmt, style, doc["title"], name, documents.MIMES[fmt], path,
             len(data), digest, brief[:2000], json.dumps(doc), library_id))
        made_id = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    return get(made_id)


def get(made_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM made_documents WHERE id = ?",
                           (made_id,)).fetchone()
    return dict(row) if row else None


def for_thread(thread_id: int) -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, format, title, filename, bytes, created_at "
            "FROM made_documents WHERE thread_id = ? ORDER BY id", (thread_id,))]


def listing(limit: int = 50) -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT m.id, m.format, m.title, m.filename, m.bytes, m.created_at, "
            "       m.thread_id, t.title AS thread "
            "FROM made_documents m LEFT JOIN chat_threads t ON t.id = m.thread_id "
            "ORDER BY m.id DESC LIMIT ?", (limit,))]


def blob(made_id: int) -> tuple[pathlib.Path, dict] | None:
    """The file on disk, if it is still there."""
    row = get(made_id)
    if row is None:
        return None
    # Rows written before the path became data-relative are stored as
    # "data/made/...", relative to the application root. Both resolve, so an
    # install that predates this keeps its documents.
    for root in (DATA_DIR, BASE_DIR):
        path = pathlib.Path(root) / row["path"]
        if path.exists():
            return path, row
    return None


def readable(size: int) -> str:
    """A size he can judge at a glance on a phone."""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"
