"""Reading meetings back out. Queries only; the worker does the writing."""
import json
from .db import cursor


def listing() -> list[dict]:
    with cursor() as conn:
        rows = conn.execute(
            "SELECT r.id, r.title, r.status, r.duration_ms, r.bytes, r.failure, "
            "       r.created_at, r.recorded_at, r.original_filename, "
            "       (SELECT COUNT(*) FROM speakers s WHERE s.recording_id = r.id) AS speakers, "
            "       (SELECT COUNT(*) FROM action_items a "
            "        WHERE a.recording_id = r.id AND a.done_at IS NULL) AS open_actions "
            "FROM recordings r "
            "ORDER BY COALESCE(r.recorded_at, r.created_at) DESC, r.id DESC"
        )
        return [dict(r) for r in rows]


def grouped() -> list[tuple[str, list[dict]]]:
    """The listing, in day buckets, in order.

    Done here rather than in the template: opening and closing a wrapper div from
    inside a Jinja loop is how you ship unbalanced HTML.
    """
    from .fmt import daygroup
    out: list[tuple[str, list[dict]]] = []
    for row in listing():
        day = daygroup(row.get("recorded_at") or row.get("created_at"))
        if not out or out[-1][0] != day:
            out.append((day, []))
        out[-1][1].append(row)
    return out


def week_ms() -> int:
    with cursor() as conn:
        return conn.execute(
            "SELECT COALESCE(SUM(duration_ms), 0) AS ms FROM recordings "
            "WHERE COALESCE(recorded_at, created_at) >= datetime('now', '-7 days')"
        ).fetchone()["ms"] or 0


def detail(recording_id: int) -> dict | None:
    with cursor() as conn:
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if rec is None:
            return None
        segments = [dict(r) for r in conn.execute(
            "SELECT idx, speaker_label, start_ms, end_ms, text FROM transcript_segments "
            "WHERE recording_id = ? ORDER BY idx", (recording_id,))]
        speakers = [dict(r) for r in conn.execute(
            "SELECT label, person_name, turns FROM speakers WHERE recording_id = ? ORDER BY label",
            (recording_id,))]
        summary = conn.execute(
            "SELECT abstract, decisions, questions, model FROM summaries WHERE recording_id = ?",
            (recording_id,)).fetchone()
        actions = [dict(r) for r in conn.execute(
            "SELECT id, text, owner, due_date, at_ms, done_at FROM action_items "
            "WHERE recording_id = ? ORDER BY id", (recording_id,))]
    return {
        "recording": dict(rec),
        "segments": segments,
        "speakers": speakers,
        "summary": {
            "abstract": summary["abstract"] if summary else "",
            "decisions": json.loads(summary["decisions"]) if summary and summary["decisions"] else [],
            "questions": json.loads(summary["questions"]) if summary and summary["questions"] else [],
            "model": summary["model"] if summary else None,
        },
        "actions": actions,
    }


def assign_speaker(recording_id: int, label: str, person_name: str | None) -> None:
    """Exact only. Two people with similar names are two people."""
    with cursor() as conn:
        conn.execute(
            "UPDATE speakers SET person_name = ? WHERE recording_id = ? AND label = ?",
            ((person_name or "").strip() or None, recording_id, label),
        )
