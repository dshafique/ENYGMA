"""One meeting as Markdown.

The escape hatch, not a second home. ENYGMA holds the meeting; this puts a
readable copy on the clipboard for the day something needs to go into a thread or
an email. Every claim keeps its timestamp, because a summary that has been pasted
somewhere else is exactly where an unsourced claim does damage.
"""
from .fmt import hms, mmss, longdate, clock


def as_markdown(data: dict) -> str:
    r = data["recording"]
    when = r.get("recorded_at") or r.get("created_at")
    lines = [f"# {r['title']}", ""]

    stamp = " · ".join(x for x in (longdate(when), clock(when), hms(r.get("duration_ms"))) if x)
    if stamp:
        lines += [stamp, ""]

    named = [s for s in data["speakers"] if s.get("person_name")]
    if named:
        lines += ["**Present:** " + ", ".join(s["person_name"] for s in named), ""]

    summary = data["summary"]
    if summary.get("abstract"):
        lines += [summary["abstract"], ""]

    if summary.get("decisions"):
        lines += ["## Decisions", ""]
        lines += [f"- {d['text']} — `{mmss(d.get('at_ms'))}`" for d in summary["decisions"]]
        lines += [""]

    if summary.get("questions"):
        lines += ["## Open questions", ""]
        lines += [f"- {q['text']} — `{mmss(q.get('at_ms'))}`" for q in summary["questions"]]
        lines += [""]

    if data["actions"]:
        lines += ["## Actions", ""]
        for a in data["actions"]:
            box = "x" if a.get("done_at") else " "
            owner = _owner(a, data["speakers"])
            tail = f" — {owner}" if owner else ""
            if a.get("due_date"):
                tail += f", due {a['due_date']}"
            lines.append(f"- [{box}] {a['text']}{tail}")
        lines += [""]

    model = summary.get("model")
    lines += ["---",
              f"Transcribed by {r.get('model') or 'unknown'}"
              + (f", summarised by {model}" if model else "")
              + ". Speaker names are assigned by hand and are not verified by the model."]
    return "\n".join(lines).rstrip() + "\n"


def _owner(action: dict, speakers: list[dict]) -> str:
    """A speaker label is meaningless outside the app. Resolve it if it has a name."""
    label = action.get("owner")
    if not label:
        return ""
    for speaker in speakers:
        if speaker.get("label") == label and speaker.get("person_name"):
            return speaker["person_name"]
    return label
