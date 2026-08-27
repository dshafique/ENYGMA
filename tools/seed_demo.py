"""Fill an empty ENYGMA with a believable week, so every surface can be judged.

Everything written here is marked source='demo' and comes out again with --clear.
Nothing is invented about the operator: no tidbits, no observations about his
strengths or weaknesses. Those stay empty until they are earned.

    python3 tools/seed_demo.py          # write the demo week
    python3 tools/seed_demo.py --clear  # remove every demo row
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import cursor, migrate  # noqa: E402
from src import chat as chat_repo, glossary  # noqa: E402

MEETINGS = [
    {
        "title": "Quarterly review with Meridian",
        "offset_days": 0, "at": "10:30", "duration_ms": 2537000,
        "speakers": {"SPEAKER 1": "Priya Raman", "SPEAKER 2": "Olena Kovalenko",
                     "SPEAKER 3": None},
        "segments": [
            ("SPEAKER 1", 0, 14000,
             "Let's start with where Q3 actually landed against the forecast."),
            ("SPEAKER 2", 14000, 39000,
             "Revenue came in about four percent under, but the shortfall is entirely "
             "the two deals that slipped into October. Underlying run rate is fine."),
            ("SPEAKER 1", 39000, 61000,
             "That matches what I have. The bigger question is the API integration "
             "with Halcyon Labs — we said end of August and that is not happening."),
            ("SPEAKER 3", 61000, 88000,
             "The blocker is on their side. Their staging environment does not "
             "support the webhook retry semantics we specified, so every failure "
             "case has to be tested by hand."),
            ("SPEAKER 2", 88000, 118000,
             "Then we move the target to the fifteenth of September and say so in "
             "writing. Quietly slipping it is how this became a problem the first time."),
            ("SPEAKER 1", 118000, 141000,
             "Agreed. I will send a revised proposal by the twenty-second with the "
             "new date and the revised scope."),
            ("SPEAKER 3", 141000, 166000,
             "Does the revised scope include the reporting module, or is that still "
             "out? I have had two people ask me this week."),
            ("SPEAKER 1", 166000, 184000,
             "Out for now. It goes in the next contract period if the integration "
             "lands cleanly."),
            ("SPEAKER 2", 184000, 212000,
             "One more thing. Who covers the integration work during the October "
             "resourcing gap? Both of the engineers who know it are away."),
            ("SPEAKER 1", 212000, 228000,
             "That is the open question. Let's not answer it badly today."),
            ("SPEAKER 3", 228000, 252000,
             "Fine. And we keep the quarterly cadence at monthly check-ins rather "
             "than going back to fortnightly."),
        ],
        "abstract": ("The quarterly review covered Q3 performance against forecast, the "
                     "API integration timeline with Halcyon Labs, and the revised proposal "
                     "scope for the next contract period. Both sides agreed the current "
                     "trajectory is on track, with one open question around resourcing "
                     "in October."),
        "decisions": [("Revised proposal to be submitted by 22 August", 118000),
                      ("API integration target moved to 15 September", 88000),
                      ("Quarterly cadence to remain at monthly check-ins", 228000)],
        "questions": [("Who covers the integration work during the October resourcing gap?", 184000),
                      ("Does the revised scope include the reporting module?", 141000)],
        "actions": [("Send the revised proposal with the new date", "SPEAKER 1", 118000, None),
                    ("Confirm Halcyon staging supports webhook retries", "SPEAKER 3", 61000, None),
                    ("Name a cover for the October resourcing gap", None, 184000, None)],
    },
    {
        "title": "Product roadmap sync",
        "offset_days": 0, "at": "14:15", "duration_ms": 1724000,
        "status": "transcribing",
        "speakers": {}, "segments": [], "abstract": "",
        "decisions": [], "questions": [], "actions": [],
    },
    {
        "title": "1:1 with Priya Raman",
        "offset_days": 1, "at": "09:00", "duration_ms": 1173000,
        "speakers": {"SPEAKER 1": "Priya Raman", "SPEAKER 2": "Yahya"},
        "segments": [
            ("SPEAKER 1", 0, 21000,
             "How are you finding the sensor pipeline work? Be honest, it is a lot "
             "of unfamiliar ground at once."),
            ("SPEAKER 2", 21000, 52000,
             "The Node-RED side clicked quickly. What I keep tripping on is MQTT — "
             "specifically what the broker does with retained messages when it restarts."),
            ("SPEAKER 1", 52000, 84000,
             "That is the right thing to be confused by. A retained message is the "
             "last known value for a topic, so a client that subscribes afterwards "
             "gets it immediately. On restart, whether it survives depends entirely "
             "on how the broker was configured to persist."),
            ("SPEAKER 2", 84000, 106000,
             "So the replay we saw last week was not a bug, it was the broker doing "
             "exactly what it was told."),
            ("SPEAKER 1", 106000, 132000,
             "Correct. Write that up — a short note on what we expect on restart. It "
             "will save the next person a day."),
            ("SPEAKER 2", 132000, 149000,
             "I will have it by Thursday."),
        ],
        "abstract": ("A check-in on the sensor pipeline work. The retained-message "
                     "replay seen last week was correct broker behaviour rather than a "
                     "fault, and the expected behaviour on restart is going to be "
                     "written down."),
        "decisions": [("Document expected broker behaviour on restart", 106000)],
        "questions": [],
        "actions": [("Write the note on retained messages and restart", "SPEAKER 2", 132000, None)],
    },
    {
        "title": "Architecture discussion",
        "offset_days": 1, "at": "15:45", "duration_ms": 3302000,
        "speakers": {"SPEAKER 1": "Olena Kovalenko", "SPEAKER 2": "Marcus Adeyemi",
                     "SPEAKER 3": "Yahya"},
        "segments": [
            ("SPEAKER 1", 0, 26000,
             "The question on the table is whether the gateway keeps doing "
             "translation, or whether devices publish in the shape we want directly."),
            ("SPEAKER 2", 26000, 61000,
             "Devices cannot. Half of them are firmware we do not control and will "
             "not see an update this year. The gateway stays."),
            ("SPEAKER 3", 61000, 88000,
             "Then the gateway becomes the thing that must never go down, which is "
             "the situation we were trying to get out of."),
            ("SPEAKER 1", 88000, 124000,
             "Two gateways, shared subscription on the broker, and the translation "
             "logic stateless so either can take the traffic. That is the shape."),
            ("SPEAKER 2", 124000, 152000,
             "Stateless is doing a lot of work in that sentence. The deduplication "
             "table is state."),
            ("SPEAKER 3", 152000, 178000,
             "It can be content addressed. Hash the payload, and a duplicate is the "
             "same row rather than a second one."),
            ("SPEAKER 1", 178000, 199000,
             "Do that. Yahya, write it up as a short design note before Friday."),
        ],
        "abstract": ("A design discussion on whether protocol translation stays in the "
                     "gateway. It does, because a large share of device firmware cannot "
                     "be updated. The agreed shape is two stateless gateways behind a "
                     "shared subscription, with deduplication done by content hash."),
        "decisions": [("Translation stays in the gateway", 26000),
                      ("Run two gateways behind a shared subscription", 88000),
                      ("Deduplicate by content hash rather than a stateful table", 152000)],
        "questions": [("What is the failover time if one gateway is lost mid-batch?", 124000)],
        "actions": [("Write the gateway design note", "SPEAKER 3", 178000, None),
                    ("Measure failover time under load", "SPEAKER 2", 124000, None)],
    },
    {
        "title": "Vendor call — Halcyon Labs",
        "offset_days": 3, "at": "11:00", "duration_ms": 1489000,
        "speakers": {"SPEAKER 1": "Marcus Adeyemi", "SPEAKER 2": "Priya Raman"},
        "segments": [
            ("SPEAKER 1", 0, 24000,
             "We need their staging to honour the retry semantics before we can "
             "certify anything end to end."),
            ("SPEAKER 2", 24000, 58000,
             "They have said twice that it is on the roadmap. I would like a date "
             "in writing this time rather than a roadmap."),
            ("SPEAKER 1", 58000, 79000,
             "I will ask for one on the call and send a summary the same day so "
             "there is a record."),
        ],
        "abstract": ("A short vendor call about staging support for webhook retry "
                     "semantics. The ask is a written date rather than a roadmap position."),
        "decisions": [("Ask for a written date rather than a roadmap position", 24000)],
        "questions": [],
        "actions": [("Send a same-day summary of the vendor call", "SPEAKER 1", 58000, None)],
    },
]


def clear() -> int:
    with cursor() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM recordings WHERE source = 'demo'")]
        for rid in ids:
            for table in ("transcript_segments", "speakers", "action_items"):
                conn.execute(f"DELETE FROM {table} WHERE recording_id = ?", (rid,))
            conn.execute("DELETE FROM summaries WHERE recording_id = ?", (rid,))
            # Threads that came out of a demo meeting go with it.
            for t in conn.execute(
                    "SELECT id FROM chat_threads WHERE recording_id = ?", (rid,)):
                conn.execute("DELETE FROM chat_messages WHERE thread_id = ?", (t["id"],))
                conn.execute("DELETE FROM chat_threads WHERE id = ?", (t["id"],))
            conn.execute("DELETE FROM recordings WHERE id = ?", (rid,))
    return len(ids)


def seed() -> int:
    migrate()
    if clear():
        print("removed the previous demo week first")
    today = datetime.now()
    written = 0
    with cursor() as conn:
        for spec in MEETINGS:
            day = today - timedelta(days=spec["offset_days"])
            recorded = f"{day:%Y-%m-%d} {spec['at']}:00"
            status = spec.get("status", "ready")
            conn.execute(
                "INSERT INTO recordings (title, recorded_at, duration_ms, status, "
                " source, original_filename, model, transcribed_at) "
                "VALUES (?, ?, ?, ?, 'demo', ?, ?, ?)",
                (spec["title"], recorded, spec["duration_ms"], status,
                 spec["title"].lower().replace(" ", "-") + ".m4a",
                 "demo" if status == "ready" else None,
                 recorded if status == "ready" else None))
            rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            written += 1

            for idx, (label, start, end, text) in enumerate(spec["segments"]):
                conn.execute(
                    "INSERT INTO transcript_segments "
                    "(recording_id, idx, speaker_label, start_ms, end_ms, text) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (rid, idx, label, start, end, text))

            turns = {}
            for label, *_ in spec["segments"]:
                turns[label] = turns.get(label, 0) + 1
            for label, name in spec["speakers"].items():
                conn.execute(
                    "INSERT INTO speakers (recording_id, label, person_name, turns) "
                    "VALUES (?, ?, ?, ?)", (rid, label, name, turns.get(label, 0)))

            if spec["abstract"] or spec["decisions"] or spec["questions"]:
                conn.execute(
                    "INSERT INTO summaries (recording_id, abstract, decisions, questions, model) "
                    "VALUES (?, ?, ?, ?, 'demo')",
                    (rid, spec["abstract"],
                     json.dumps([{"text": t, "at_ms": ms} for t, ms in spec["decisions"]]),
                     json.dumps([{"text": t, "at_ms": ms} for t, ms in spec["questions"]])))

            for text, owner, at_ms, due in spec["actions"]:
                conn.execute(
                    "INSERT INTO action_items (recording_id, text, owner, at_ms, due_date) "
                    "VALUES (?, ?, ?, ?, ?)", (rid, text, owner, at_ms, due))

    _seed_thread()
    return written


def _seed_thread() -> None:
    """One thread, so Chat is not a blank room.

    The answer is the real glossary answer, produced by the real code path — not a
    transcript of a conversation that never happened.
    """
    glossary.seed_if_empty()
    with cursor() as conn:
        row = conn.execute(
            "SELECT id FROM recordings WHERE source = 'demo' "
            "AND title LIKE '1:1%'").fetchone()
    if row is None:
        return
    thread_id = chat_repo.start("MQTT", seed_term="MQTT", recording_id=row["id"])
    chat_repo.say(thread_id, "What is MQTT?")
    chat_repo.say(thread_id, "What is a retained message?")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        print(f"removed {clear()} demo recording(s)")
    else:
        print(f"wrote {seed()} demo recording(s). Remove with --clear.")
