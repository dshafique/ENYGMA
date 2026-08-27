"""Formatting for templates.

Kept in Python rather than Jinja because a clock that is wrong is worse than a
clock that is missing, and Python can be tested.
"""
from datetime import datetime, timezone, timedelta


def hms(ms: int | None) -> str:
    """00:42:17 — always three fields, so a column of them lines up."""
    if not ms:
        return "00:00:00"
    total = int(ms) // 1000
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def mmss(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    total = int(ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def hours(ms: int | None) -> str:
    if not ms:
        return "0"
    value = ms / 3_600_000
    return f"{value:.1f}".rstrip("0").rstrip(".") or "0"


def _parse(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ").replace("Z", "")
    for shape, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16),
                         ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(text[:width], shape)
        except ValueError:
            continue
    return None


def clock(value) -> str:
    """9:00 AM. Empty string if the timestamp will not parse; never a guess."""
    at = _parse(value)
    return at.strftime("%-I:%M %p") if at else ""


def longdate(value) -> str:
    at = _parse(value)
    return at.strftime("%a %-d %b").upper() if at else ""


def daygroup(value) -> str:
    """TODAY / YESTERDAY / THU 21 AUG. The heading a list is grouped under."""
    at = _parse(value)
    if at is None:
        return "UNDATED"
    today = datetime.now(timezone.utc).date()
    delta = (today - at.date()).days
    if delta <= 0:
        return "TODAY"
    if delta == 1:
        return "YESTERDAY"
    if delta < 7:
        return at.strftime("%A").upper()
    return at.strftime("%a %-d %b").upper()


def ago(value) -> str:
    at = _parse(value)
    if at is None:
        return ""
    delta = datetime.now(timezone.utc).replace(tzinfo=None) - at
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta < timedelta(days=1):
        return f"{int(delta.total_seconds() // 3600)} h ago"
    if delta.days == 1:
        return "yesterday"
    if delta.days < 30:
        return f"{delta.days} days ago"
    return longdate(value)


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


FILTERS = {
    "hms": hms, "mmss": mmss, "hours": hours, "clock": clock,
    "longdate": longdate, "daygroup": daygroup, "ago": ago, "initials": initials,
}
