"""The worker: queued -> transcribing -> ready, or failed with a reason.

One recording at a time, on a background thread. One operator, one machine; a job
queue would be more machinery than the problem has.
"""
from __future__ import annotations

import json
import threading
import time
import traceback

from ..config import config, BASE_DIR
from ..db import cursor
from ..ingest import notes as notes_ingest
from .base import Segment, Transcript
from .gemini import get_backend

_stop = threading.Event()
_thread: threading.Thread | None = None


def requeue_stuck() -> int:
    """Anything left mid-flight belongs back in the queue.

    A recording is marked 'transcribing' before the work starts. If the process
    dies in between -- a restart, the memory ceiling, a power cut -- that row
    stays 'transcribing' forever: the worker only claims 'queued', so nothing
    ever picks it up again and the interface shows a progress bar that will
    never finish. Called once at startup, before the worker begins.
    """
    with cursor() as conn:
        rows = conn.execute(
            "SELECT id, title FROM recordings WHERE status = 'transcribing'").fetchall()
        if rows:
            conn.execute(
                "UPDATE recordings SET status = 'queued', "
                "failure = 'Interrupted before it finished; picked up again on restart.' "
                "WHERE status = 'transcribing'")
    for row in rows:
        print(f"requeued interrupted recording {row['id']}: {row['title']}")
    return len(rows)


def claim_next() -> dict | None:
    """Take one queued recording and mark it in progress, atomically."""
    with cursor() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT id, audio_path, mime, title, source, source_text "
                "FROM recordings WHERE status = 'queued' "
                "  AND (audio_path IS NOT NULL OR source_text IS NOT NULL) "
                "ORDER BY id LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            conn.execute(
                "UPDATE recordings SET status = 'transcribing', failure = NULL WHERE id = ?",
                (row["id"],),
            )
            conn.execute("COMMIT")
            return dict(row)
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _write_results(recording_id: int, transcript, summary) -> None:
    with cursor() as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM transcript_segments WHERE recording_id = ?", (recording_id,))
            conn.execute("DELETE FROM speakers WHERE recording_id = ?", (recording_id,))
            conn.execute("DELETE FROM action_items WHERE recording_id = ? AND done_at IS NULL",
                         (recording_id,))
            for i, seg in enumerate(transcript.segments):
                conn.execute(
                    "INSERT INTO transcript_segments "
                    "(recording_id, idx, speaker_label, start_ms, end_ms, text) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (recording_id, i, seg.speaker_label, seg.start_ms, seg.end_ms, seg.text),
                )
            for label in transcript.speaker_labels:
                turns = sum(1 for s in transcript.segments if s.speaker_label == label)
                conn.execute(
                    "INSERT OR REPLACE INTO speakers (recording_id, label, turns) VALUES (?, ?, ?)",
                    (recording_id, label, turns),
                )
            conn.execute(
                "INSERT OR REPLACE INTO summaries "
                "(recording_id, abstract, decisions, questions, model) VALUES (?, ?, ?, ?, ?)",
                (recording_id, summary.abstract, json.dumps(summary.decisions),
                 json.dumps(summary.questions), summary.model),
            )
            for action in summary.actions:
                conn.execute(
                    "INSERT INTO action_items (recording_id, text, owner, at_ms) VALUES (?, ?, ?, ?)",
                    (recording_id, action["text"], action.get("owner"), action.get("at_ms")),
                )
            was_notes = conn.execute(
                "SELECT source_text FROM recordings WHERE id = ?",
                (recording_id,)).fetchone()["source_text"]
            last = transcript.segments[-1] if transcript.segments else None
            conn.execute(
                "UPDATE recordings SET status = 'ready', transcribed_at = datetime('now'), "
                "model = ?, duration_ms = COALESCE(duration_ms, ?), note = ? WHERE id = ?",
                (transcript.model, (last.end_ms if last else None),
                 " ".join(x for x in (
                     getattr(transcript, "note", None),
                     ("This meeting started as notes. The recording arrived "
                      "afterwards, and this transcript is from the audio; the "
                      "original notes are still on the Notes tab."
                      ) if was_notes else None) if x) or None,
                 recording_id),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def process_one(backend=None) -> dict | None:
    job = claim_next()
    if job is None:
        return None
    backend = backend or get_backend()
    try:
        # Audio wins when a meeting has both: a transcript with timestamps is
        # strictly better than notes about the same hour, and the notes are kept.
        if not job.get("audio_path") and job.get("source_text"):
            return _process_notes(job, backend)
        path = BASE_DIR / job["audio_path"]
        transcript = backend.transcribe(path, job["mime"] or "audio/mpeg")
        summary = backend.summarise(transcript)
        _write_results(job["id"], transcript, summary)
        return {"id": job["id"], "status": "ready", "segments": len(transcript.segments)}
    except Exception as exc:
        # The message is what the interface shows, so it names the thing and the
        # place. "Transcription error" is not a usable sentence.
        reason = f"{type(exc).__name__}: {exc}"[:400]
        with cursor() as conn:
            conn.execute(
                "UPDATE recordings SET status = 'failed', failure = ? WHERE id = ?",
                (reason, job["id"]),
            )
        return {"id": job["id"], "status": "failed", "detail": reason}


def _process_notes(job: dict, backend) -> dict:
    """A meeting that arrived as notes. Same destination, different road.

    The notes themselves become the segments, so the reader, the search and the
    hold-a-word popover work exactly as they do for a transcript. They carry no
    timestamps, and every claim drawn from them carries none either, because
    there is no recording for one to point at.
    """
    text = job["source_text"] or ""
    read = backend.digest_notes(text)

    blocks = notes_ingest.paragraphs(text)
    transcript = Transcript(
        segments=[Segment(speaker_label="NOTES", start_ms=None, end_ms=None, text=b)
                  for b in blocks],
        model=read["summary"].model or "notes",
        note=("This meeting came from notes, not a recording. There is no audio "
              "to check any of it against, and nothing here carries a timestamp."),
    )
    _write_results(job["id"], transcript, read["summary"])

    with cursor() as conn:
        if read["title"]:
            conn.execute("UPDATE recordings SET title = ? WHERE id = ?",
                         (read["title"][:200], job["id"]))
        if read["date"]:
            conn.execute(
                "UPDATE recordings SET recorded_at = ? WHERE id = ?",
                (f"{read['date']} 00:00:00", job["id"]))
        # Attendees are people who were in the room, which is not the same claim
        # as having spoken. turns stays 0 and the interface says "attended".
        conn.execute("DELETE FROM speakers WHERE recording_id = ?", (job["id"],))
        for i, name in enumerate(read["attendees"], start=1):
            conn.execute(
                "INSERT OR REPLACE INTO speakers (recording_id, label, person_name, turns) "
                "VALUES (?, ?, ?, 0)", (job["id"], f"ATTENDEE {i}", name))
        conn.execute(
            "UPDATE recordings SET duration_ms = NULL, note = ? WHERE id = ?",
            (transcript.note, job["id"]))
    return {"id": job["id"], "status": "ready", "segments": len(blocks), "kind": "notes"}


def drain(limit: int = 100, backend=None) -> list[dict]:
    out = []
    for _ in range(limit):
        result = process_one(backend)
        if result is None:
            break
        out.append(result)
    return out


# The Friday note rides on this thread rather than getting a scheduler of its
# own. It is checked only when the queue is empty, and at most once every few
# minutes, so it can never delay a transcription or hammer the model.
_WEEKNOTE_EVERY = 300.0
_last_weeknote_check = 0.0


def _maybe_weeknote() -> None:
    """Write the week's note if a finished week is missing one.

    Deliberately not driven by a clock alarm: the Spark can be asleep at three on
    a Friday, and an alarm that fires into a sleeping machine writes nothing and
    says nothing. Asking "is there a finished week without a note" instead means
    a missed Friday becomes a note waiting for him on Sunday.
    """
    global _last_weeknote_check
    now = time.monotonic()
    if now - _last_weeknote_check < _WEEKNOTE_EVERY:
        return
    _last_weeknote_check = now
    from .. import weeknote
    written = weeknote.write_if_due()
    if written:
        print(f"wrote the week note for {written['week_start']}")


def _loop() -> None:
    while not _stop.is_set():
        try:
            if process_one() is None:
                # Only when there is no transcription waiting: his audio is the
                # thing he is standing there watching, and it goes first.
                _maybe_weeknote()
                _stop.wait(config.WORKER_POLL_SECONDS)
        except Exception:
            traceback.print_exc()
            _stop.wait(config.WORKER_POLL_SECONDS)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    requeue_stuck()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="enygma-worker", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
