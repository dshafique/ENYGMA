"""The library: documents and notes ENYGMA can draw on when it answers.

A meeting records something that happened. A document is context that was already
true — a spec, a runbook, an onboarding note, a paper somebody sent. Without one
of these, Chat could only answer from a small glossary and whatever the model
already knew, which is to say it knew nothing about the operator's own work.

Retrieval is SQLite's full-text index with stemming, not vector embeddings. For
one person with tens of documents that finds the right passage, costs nothing per
query, needs no API key, keeps working when the model is unreachable, and can be
reasoned about when it returns the wrong thing. Embeddings are the upgrade if
recall ever turns out to be the weak link, and the interface here does not care
which is underneath.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .db import cursor

# Long enough to hold an argument, short enough that several fit in a prompt.
CHUNK_WORDS = 220
CHUNK_OVERLAP_WORDS = 40

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".log",
                 ".json", ".yaml", ".yml", ".py", ".js", ".sql", ".sh", ".ini",
                 ".toml", ".cfg"}


class Rejected(ValueError):
    """This file will never be readable. Says why, in a sentence."""


# --------------------------------------------------------------------------
# getting text out of a file
# --------------------------------------------------------------------------
def _from_html(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    return html.unescape(text)


def _from_pdf(raw: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise Rejected(
            "This host cannot read PDFs: pdftotext is not installed. "
            "Install poppler-utils, or paste the text in as a note."
        )
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "in.pdf"
        source.write_bytes(raw)
        out = subprocess.run(["pdftotext", "-layout", str(source), "-"],
                             capture_output=True, timeout=300)
        if out.returncode != 0:
            raise Rejected("That PDF could not be read. It may be scanned images "
                           "rather than text.")
        return out.stdout.decode("utf-8", errors="replace")


def extract(filename: str, raw: bytes) -> str:
    """Text out of a file, or a sentence saying why not."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = _from_pdf(raw)
    elif suffix in (".html", ".htm"):
        text = _from_html(raw)
    elif suffix == ".json":
        try:
            text = json.dumps(json.loads(raw.decode("utf-8")), indent=2)
        except (ValueError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")
    elif suffix in TEXT_SUFFIXES:
        text = raw.decode("utf-8", errors="replace")
    else:
        raise Rejected(
            f"{suffix or 'That file'} is not something ENYGMA can read as text. "
            "Text, Markdown, HTML, JSON, CSV and PDF work; anything else, paste "
            "the part that matters in as a note."
        )
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise Rejected("There was no readable text in that file.")
    return text


# --------------------------------------------------------------------------
# storing
# --------------------------------------------------------------------------
def chunk(text: str) -> list[str]:
    """Overlapping passages. The overlap keeps a sentence that straddles a
    boundary findable from either side."""
    words = text.split()
    if not words:
        return []
    step = max(1, CHUNK_WORDS - CHUNK_OVERLAP_WORDS)
    out = []
    for start in range(0, len(words), step):
        piece = words[start:start + CHUNK_WORDS]
        if piece:
            out.append(" ".join(piece))
        if start + CHUNK_WORDS >= len(words):
            break
    return out


def add(title: str, body: str, *, kind: str = "note", source_name: str | None = None,
        mime: str | None = None, raw: bytes | None = None,
        note: str | None = None) -> dict:
    """Add a document. Content addressed, so the same file twice is one entry."""
    title = (title or "").strip() or (source_name or "Untitled")
    body = (body or "").strip()
    if not body:
        raise Rejected("There is nothing in that.")

    digest = hashlib.sha256(raw if raw is not None else body.encode()).hexdigest()
    with cursor() as conn:
        existing = conn.execute(
            "SELECT id, title FROM documents WHERE sha256 = ?", (digest,)).fetchone()
        if existing:
            return {"id": existing["id"], "title": existing["title"], "duplicate": True}

        conn.execute(
            "INSERT INTO documents (title, kind, source_name, mime, sha256, bytes, "
            " body, words, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title[:200], kind, source_name, mime, digest,
             len(raw) if raw is not None else len(body.encode()),
             body, len(body.split()), note))
        document_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        pieces = chunk(body)
        for i, piece in enumerate(pieces):
            conn.execute(
                "INSERT INTO document_chunks (document_id, idx, text) VALUES (?, ?, ?)",
                (document_id, i, piece))
    return {"id": document_id, "title": title, "duplicate": False, "chunks": len(pieces)}


def remove(document_id: int) -> bool:
    with cursor() as conn:
        conn.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return conn.execute("SELECT changes() AS n").fetchone()["n"] > 0


def listing() -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT d.id, d.title, d.kind, d.source_name, d.words, d.bytes, "
            "       d.note, d.added_at, "
            "       (SELECT COUNT(*) FROM document_chunks c WHERE c.document_id = d.id) AS chunks "
            "FROM documents d ORDER BY d.added_at DESC, d.id DESC")]


def get(document_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    return dict(row) if row else None


def total_words() -> int:
    with cursor() as conn:
        return conn.execute(
            "SELECT COALESCE(SUM(words), 0) AS n FROM documents").fetchone()["n"]


# --------------------------------------------------------------------------
# finding
# --------------------------------------------------------------------------
# Words that appear in every question and therefore distinguish nothing. Without
# this list a question about swallows matches a document about message brokers,
# because both contain "what" and "the" -- and the answer then cites a source it
# has no business citing, which is worse than having no source at all.
STOPWORDS = frozenset("""
about above after again against all also and any are because been before being
below between both but can cant come could did does doing done dont down during
each few for from further get got had has have having her here hers him his
how into its itself just like made make many may might more most much must not
now off once only other our out over own said same should since some such than
that the their them then there these they thing things this those through too
under until use used using very was way well were what when where which while
who whom why will with without would you your yours
""".split())


def _terms(text: str) -> list[str]:
    """The words in a question that actually narrow it down."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'_-]*", text or "")
    return [w for w in words if len(w) > 2 and w.lower() not in STOPWORDS][:24]


def _query(text: str) -> str:
    """A question in English, as an FTS query.

    FTS5 treats bare punctuation and its own keywords as syntax, so every term is
    quoted to keep it literal. They are OR-ed so one unusual word in a long
    question is enough to find the passage.
    """
    terms = _terms(text)
    if not terms:
        return ""
    return " OR ".join(f'"{w}"' for w in terms)


# A word in at most this share of the library's passages is distinctive enough
# that finding it once is real evidence rather than a coincidence.
RARE_ENOUGH = 0.34


def _document_frequency(term: str) -> float:
    """What share of passages contain this word. 1.0 means it says nothing."""
    with cursor() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM document_chunks").fetchone()["n"]
        if not total:
            return 1.0
        try:
            hits = conn.execute(
                "SELECT COUNT(*) AS n FROM chunk_search WHERE chunk_search MATCH ?",
                (f'"{term}"',)).fetchone()["n"]
        except Exception:
            return 1.0
    return hits / total


def search(question: str, limit: int = 6) -> list[dict]:
    """The best passages for a question, best first."""
    query = _query(question)
    if not query:
        return []
    with cursor() as conn:
        try:
            rows = conn.execute(
                "SELECT c.id, c.document_id, c.idx, c.text, d.title, d.kind, "
                "       bm25(chunk_search) AS score "
                "FROM chunk_search s "
                "JOIN document_chunks c ON c.id = s.rowid "
                "JOIN documents d ON d.id = c.document_id "
                "WHERE chunk_search MATCH ? ORDER BY score LIMIT ?",
                (query, limit)).fetchall()
        except Exception:
            # A malformed query is not worth failing an answer over.
            return []
    return [dict(r) for r in rows]


def context_for(question: str, limit: int = 5, budget_words: int = 1400) -> dict:
    """Passages to put in a prompt, and which documents they came from.

    A passage earns its place by sharing more than one of the question's
    distinctive words, or by sharing a single word that is rare across the whole
    library. "Gateway" appearing in one document out of forty is strong evidence;
    "system" appearing in all of them is none. A coincidence presented as a source
    is exactly the confident wrongness this system is supposed to refuse.
    """
    asked = [w.lower() for w in _terms(question)]
    if not asked:
        return {"text": "", "sources": []}
    rare = {w for w in asked if _document_frequency(w) <= RARE_ENOUGH}

    hits = []
    for hit in search(question, limit=limit * 3):
        body = hit["text"].lower()
        present = {w for w in asked if w in body}
        if len(present) >= 2 or (present & rare):
            hits.append(hit)
        if len(hits) >= limit:
            break
    used, sources, spent = [], {}, 0
    for hit in hits:
        words = len(hit["text"].split())
        if spent + words > budget_words:
            continue
        used.append(hit)
        spent += words
        sources.setdefault(hit["document_id"], hit["title"])
    if not used:
        return {"text": "", "sources": []}
    body = "\n\n".join(f'From "{h["title"]}":\n{h["text"]}' for h in used)
    return {"text": body,
            "sources": [{"id": k, "title": v} for k, v in sources.items()]}
