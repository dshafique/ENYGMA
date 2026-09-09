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

The mark on a new entry is written as UNRELEASED and filled in by
tools/stamp_release.py at the moment the build number is decided. Writing it by
hand looked fine and was wrong: the number comes from the commit count, so the
very act of committing the changelog entry changed the number the entry claimed.
Once a mark has been assigned it is never rewritten, because a device that has
already been shown a release must not be shown it again under a new number.
"""
from __future__ import annotations

# Newest first. `mark` matches the build stamp so a device can tell what it has
# already been shown.
UNRELEASED = "UNRELEASED"

RELEASES = [
    {
        "mark": "Mk II.44",
        "date": "2026-09-09",
        "headline": "Yours, theirs, and ours",
        "items": [
            "Action items filter to Mine or Theirs. Anything the team took on "
            "together counts as yours, because it is yours to chase.",
            "Every part of ENYGMA that writes something you act on now works to "
            "the same rule: add nothing that was not said, and drop nothing that "
            "was.",
        ],
    },
    {
        "mark": "Mk II.43",
        "date": "2026-09-09",
        "headline": "Summaries that keep what was said",
        "items": [
            "Meeting summaries now walk through what was discussed, subject by "
            "subject, instead of three sentences and nothing else.",
            "Action items are no longer dropped for having no clear moment or no "
            "single owner. Things the team agreed to count.",
            "Summarise again, on any meeting, rewrites the summary from the "
            "transcript already stored. It never re-reads the audio.",
        ],
    },
    {
        "mark": "Mk II.42",
        "date": "2026-09-05",
        "headline": "Your fingerprint works in the app",
        "items": [
            "Passkeys work inside the installed app now, not just in a browser, "
            "so you can unlock with your fingerprint again.",
            "The PIN still works and is still there if the fingerprint is not.",
        ],
    },
    {
        "mark": "Mk II.41",
        "date": "2026-09-05",
        "headline": "Getting in, and staying in",
        "items": [
            "The PIN on the lock screen works. It never did, which in the app "
            "meant there was no way in at all.",
            "The passkey button is hidden where a passkey cannot happen, "
            "instead of sitting there doing nothing.",
            "Working keeps you signed in. You are only asked again after you "
            "have actually stopped for a while.",
        ],
    },
    {
        "mark": "Mk II.40",
        "date": "2026-09-04",
        "headline": "A nudge on Friday",
        "items": [
            "The app reminds you on Friday afternoon that your week is written, "
            "so you can read it and send it.",
            "It comes from your phone, not from ENYGMA, so nothing about your "
            "week leaves the Spark to make it happen.",
            "Bench items show their number at the front of the line, so you can "
            "point at one by saying it.",
        ],
    },
    {
        "mark": "Mk II.39",
        "date": "2026-09-04",
        "headline": "Record a meeting from inside ENYGMA",
        "items": [
            "Meetings has a record button. Press it, put the phone down, press "
            "stop, and it lands here as a meeting.",
            "Pause and resume while it runs, or discard it without saving.",
            "In the browser it records only while the page is open. The "
            "installed app keeps going with the screen off.",
        ],
    },
    {
        "mark": "Mk II.38",
        "date": "2026-09-04",
        "headline": "Answers arrive as they are written",
        "items": [
            "Chat writes the answer out as it comes rather than making you wait "
            "for all of it.",
            "The send button becomes a stop button while it writes. Press it and "
            "it keeps what had arrived.",
            "A stopped answer is marked, so the next question knows where it "
            "was cut off.",
        ],
    },
    {
        "mark": "Mk II.37",
        "date": "2026-09-04",
        "headline": "Write your own week",
        "items": [
            "Your week card has a box you can type into. Write roughly what you "
            "did, one line each, and it lays it out as the note.",
            "It uses your words and does not add any of its own.",
            "Write it again still brings back the one ENYGMA built for you.",
            "Chat lost a strip of empty space above the writing bar.",
        ],
    },
    {
        "mark": "Mk II.34",
        "date": "2026-09-04",
        "headline": "Rotation, the keyboard, and what it costs",
        "items": [
            "The app follows your phone's rotation lock instead of overriding it.",
            "The writing bar stays above the keyboard, on any browser.",
            "Home shows what the paid models have cost this month.",
            "The Bench has filters. The chips above the list are filters now, and "
            "the ones inside the Add box set what you are adding.",
        ],
    },
    {
        "mark": "Mk II.30",
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


def released() -> list[dict]:
    """Everything that has actually been stamped. An entry still marked
    UNRELEASED is one being written, and has no number to compare against."""
    return [r for r in RELEASES if r["mark"] != UNRELEASED]


def since(mark: str | None) -> list[dict]:
    """Everything newer than the build this device last saw.

    An unknown mark means a device that has never been here, or one that has not
    opened the app since before any of this was written down. Either way there
    is nothing useful to catch it up on, so it is shown nothing and quietly
    marked as current: a wall of history is not a welcome.
    """
    if not mark:
        return []
    out = released()
    known = [r["mark"] for r in out]
    if mark not in known:
        return []
    return out[:known.index(mark)]


def latest() -> str:
    out = released()
    return out[0]["mark"] if out else ""
