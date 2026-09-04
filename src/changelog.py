"""What changed, said once per device.

He deploys and Yahya opens the app to find it different. Without this, a feature
either gets discovered by accident or does not get discovered at all: the file
button in the header, the model picker, the fact that a photograph can now be
asked about. All of those were built and none of them announce themselves.

Written by hand rather than generated from commits. The commit messages in this
project are long-form prose about why something is the way it is, aimed at
whoever maintains it. This is aimed at the person using it, and the two are
different documents even when they describe the same change.

Rules for entries: what he can now do, in his words, in one line. Not what was
refactored, not what was fixed unless he felt it, and never more than five lines
for a release. A changelog nobody finishes is a changelog nobody reads.
"""
from __future__ import annotations

# Newest first. `mark` matches the build stamp so a device can tell what it has
# already been shown.
RELEASES = [
    {
        "mark": "Mk II.29",
        "date": "2026-09-04",
        "headline": "The bench, and a say in who answers",
        "items": [
            "New Bench tab: a backlog for bugs and ideas, and somewhere to keep notes.",
            "Attach a photo or a file to a question in Chat, and ask about it.",
            "Choose who answers each thread: Local, Gemini or Opus. Local is the "
            "default and never leaves the Spark.",
            "Chat says when the paid models pass another ten dollars in a month.",
        ],
    },
    {
        "mark": "Mk II.25",
        "date": "2026-09-02",
        "headline": "Documents, and a writing bar that stays put",
        "items": [
            "Ask for a file and get one: Markdown, Word, PowerPoint, Excel, PDF "
            "or a web page.",
            "Files live behind the button in the thread header.",
            "The writing bar no longer disappears below a long conversation.",
            "Return starts a new line. The send button sends.",
        ],
    },
    {
        "mark": "Mk II.18",
        "date": "2026-09-01",
        "headline": "Your week, written for you",
        "items": [
            "Friday afternoon, Home carries a note on what you got done and what "
            "is next, ready to paste into an email.",
            "A meeting you only have notes for can still be filed, and can take "
            "its recording later.",
        ],
    },
]


def since(mark: str | None) -> list[dict]:
    """Everything newer than the build this device last saw.

    An unknown mark means a device that has never been here, or one that has not
    opened the app since before any of this was written down. Either way there
    is nothing useful to catch it up on, so it is shown nothing and quietly
    marked as current: a wall of history is not a welcome.
    """
    if not mark:
        return []
    known = [r["mark"] for r in RELEASES]
    if mark not in known:
        return []
    return RELEASES[:known.index(mark)]


def latest() -> str:
    return RELEASES[0]["mark"] if RELEASES else ""
