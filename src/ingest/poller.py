"""The poller: pull the list, download what is new, record what happened.

Two outcomes must never be confusable, in the log or in the interface:

    nothing_new           the account has no recordings we have not seen
    credentials_expired   the token is dead and nothing will ever arrive

They are different facts. One is fine, the other means the product silently
stopped working. See the interface brief, section C4.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import BASE_DIR
from ..db import cursor
from .hinotes import HiNotes, CredentialsExpired, HiNotesUnavailable

UPLOADS = BASE_DIR / "uploads"

# HiNotes has used a few key spellings. Take the first that is present rather
# than assuming one, and fail loudly if none is.
ID_KEYS = ("noteId", "note_id", "id")
TITLE_KEYS = ("noteTitle", "title", "name")
TIME_KEYS = ("createTime", "createtime", "created_at", "recordTime")
DURATION_KEYS = ("duration", "durationMs", "recordDuration")


def _first(row: dict, keys: tuple[str, ...]):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _normalise(row: dict) -> dict:
    source_id = _first(row, ID_KEYS)
    if source_id is None:
        raise HiNotesUnavailable("A listed recording had no id under any known key")
    title = _first(row, TITLE_KEYS) or "Untitled recording"
    # The .hda extension is a red herring: the server transcodes to MP3 on the way
    # out. Strip it from the title so it never reaches the interface.
    if isinstance(title, str) and title.lower().endswith(".hda"):
        title = title[:-4]
    duration = _first(row, DURATION_KEYS)
    try:
        duration_ms = int(duration) if duration is not None else None
        if duration_ms is not None and duration_ms < 10_000:
            duration_ms *= 1000  # some payloads report seconds
    except (TypeError, ValueError):
        duration_ms = None
    return {
        "source_id": str(source_id),
        "title": title,
        "recorded_at": _first(row, TIME_KEYS),
        "duration_ms": duration_ms,
    }


def _portable(path: Path) -> str:
    """Store paths relative to BASE_DIR so a second checkout isolates them for free.

    Falls back to absolute when the uploads directory has been pointed elsewhere,
    which only happens under test.
    """
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return path.as_posix()


def _log(outcome: str, detail: str | None = None, count: int = 0) -> None:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO ingest_log (outcome, detail, count) VALUES (?, ?, ?)",
            (outcome, detail, count),
        )


def _known_ids() -> set[str]:
    with cursor() as conn:
        return {r["source_id"] for r in conn.execute(
            "SELECT source_id FROM recordings WHERE source_id IS NOT NULL")}


def _insert(rec: dict) -> int:
    with cursor() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO recordings "
            "(source_id, title, recorded_at, duration_ms, status) "
            "VALUES (?, ?, ?, ?, 'queued')",
            (rec["source_id"], rec["title"], rec["recorded_at"], rec["duration_ms"]),
        )
        row = conn.execute(
            "SELECT id FROM recordings WHERE source_id = ?", (rec["source_id"],)
        ).fetchone()
        return row["id"]


def _store_audio(client: HiNotes, recording_id: int, source_id: str) -> int:
    UPLOADS.mkdir(parents=True, exist_ok=True)
    audio = client.download_audio(source_id)
    # The name is derived, not taken from the payload: a title is user input.
    stem = hashlib.sha256(source_id.encode()).hexdigest()[:16]
    path = UPLOADS / f"{stem}.mp3"
    path.write_bytes(audio)
    with cursor() as conn:
        conn.execute(
            "UPDATE recordings SET audio_path = ?, bytes = ? WHERE id = ?",
            (_portable(path), len(audio), recording_id),
        )
    return len(audio)


def pull_once(client: HiNotes | None = None) -> dict:
    """One pass. Returns {'outcome', 'count', 'detail'} and always logs it."""
    owned = client is None
    try:
        client = client or HiNotes()
    except Exception as exc:
        _log("error", str(exc))
        return {"outcome": "error", "count": 0, "detail": str(exc)}

    try:
        try:
            rows = client.list_recordings()
        except CredentialsExpired as exc:
            # The important branch. Never let this land as nothing_new.
            _log("credentials_expired", str(exc))
            return {"outcome": "credentials_expired", "count": 0, "detail": str(exc)}
        except HiNotesUnavailable as exc:
            _log("error", str(exc))
            return {"outcome": "error", "count": 0, "detail": str(exc)}

        known = _known_ids()
        fresh = []
        for row in rows:
            rec = _normalise(row)
            if rec["source_id"] not in known:
                fresh.append(rec)

        if not fresh:
            _log("nothing_new")
            return {"outcome": "nothing_new", "count": 0, "detail": None}

        pulled = 0
        for rec in fresh:
            recording_id = _insert(rec)
            try:
                _store_audio(client, recording_id, rec["source_id"])
                pulled += 1
            except CredentialsExpired as exc:
                _log("credentials_expired", str(exc), pulled)
                return {"outcome": "credentials_expired", "count": pulled, "detail": str(exc)}
            except HiNotesUnavailable as exc:
                # The row stays queued with no audio. The next pass retries it.
                with cursor() as conn:
                    conn.execute(
                        "UPDATE recordings SET failure = ? WHERE id = ?",
                        (str(exc), recording_id),
                    )
        _log("pulled", None, pulled)
        return {"outcome": "pulled", "count": pulled, "detail": None}
    finally:
        if owned:
            client.close()


def status() -> dict:
    with cursor() as conn:
        last_ok = conn.execute(
            "SELECT ran_at, count FROM ingest_log WHERE outcome = 'pulled' "
            "ORDER BY ran_at DESC LIMIT 1"
        ).fetchone()
        last = conn.execute(
            "SELECT ran_at, outcome, detail FROM ingest_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM recordings WHERE audio_path IS NULL"
        ).fetchone()["n"]
        recent = [dict(r) for r in conn.execute(
            "SELECT ran_at, outcome, count, detail FROM ingest_log ORDER BY id DESC LIMIT 10")]
    return {
        "last_successful_pull": last_ok["ran_at"] if last_ok else None,
        "last_outcome": last["outcome"] if last else None,
        "credentials_ok": (last["outcome"] != "credentials_expired") if last else None,
        "pending": pending,
        "log": recent,
    }


if __name__ == "__main__":
    from ..db import migrate
    migrate()
    print(pull_once())
