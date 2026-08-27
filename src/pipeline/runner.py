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
                "SELECT id, audio_path, mime, title FROM recordings "
                "WHERE status = 'queued' AND audio_path IS NOT NULL "
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
            last = transcript.segments[-1] if transcript.segments else None
            conn.execute(
                "UPDATE recordings SET status = 'ready', transcribed_at = datetime('now'), "
                "model = ?, duration_ms = COALESCE(duration_ms, ?) WHERE id = ?",
                (transcript.model, (last.end_ms if last else None), recording_id),
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


def drain(limit: int = 100, backend=None) -> list[dict]:
    out = []
    for _ in range(limit):
        result = process_one(backend)
        if result is None:
            break
        out.append(result)
    return out


def _loop() -> None:
    while not _stop.is_set():
        try:
            if process_one() is None:
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
