"""The Directory.

Everyone who has spoken in a meeting, with the meetings they appeared in. A person
exists because a speaker label was given a name; nothing is merged automatically,
because two similar names are two people until he says otherwise.
"""
from .db import cursor


def listing() -> list[dict]:
    with cursor() as conn:
        rows = conn.execute(
            "SELECT s.person_name AS name, COUNT(DISTINCT s.recording_id) AS meetings, "
            "       SUM(s.turns) AS turns, MAX(r.recorded_at) AS last_seen "
            "FROM speakers s JOIN recordings r ON r.id = s.recording_id "
            "WHERE s.person_name IS NOT NULL AND TRIM(s.person_name) <> '' "
            "GROUP BY s.person_name ORDER BY meetings DESC, s.person_name"
        )
        people = [dict(r) for r in rows]
        meta = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM people")}
        for person in people:
            extra = meta.get(person["name"], {})
            person["role"] = extra.get("role")
            person["org"] = extra.get("org")
            person["note"] = extra.get("note")
            person["initials"] = _initials(person["name"])
            person["recent"] = [dict(x) for x in conn.execute(
                "SELECT r.id, r.title, r.recorded_at FROM speakers s "
                "JOIN recordings r ON r.id = s.recording_id "
                "WHERE s.person_name = ? ORDER BY r.recorded_at DESC LIMIT 4",
                (person["name"],))]
        unnamed = conn.execute(
            "SELECT COUNT(*) AS n FROM speakers "
            "WHERE person_name IS NULL OR TRIM(person_name) = ''").fetchone()["n"]
    return people, unnamed


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def upsert(name: str, role: str | None, org: str | None, note: str | None) -> None:
    name = (name or "").strip()
    if not name:
        return
    with cursor() as conn:
        conn.execute(
            "INSERT INTO people (name, role, org, note) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET role = excluded.role, "
            "org = excluded.org, note = excluded.note",
            (name, (role or "").strip() or None, (org or "").strip() or None,
             (note or "").strip() or None),
        )
