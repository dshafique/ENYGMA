"""Show how speaker attribution behaves across a recording.

Written to answer one question: after roughly the thirty minute mark, every
segment is attributed to the same speaker. Diarization on this platform is
documented as working up to thirty minutes; beyond it the model keeps emitting
whichever label it used last. This prints the evidence rather than the theory.

    python3 tools/inspect_transcript.py            # list recordings
    python3 tools/inspect_transcript.py 12         # analyse one
    python3 tools/inspect_transcript.py 12 --text  # with the first words of each turn
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import cursor  # noqa: E402

BUCKET_MIN = 5


def clock(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    total = int(ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def listing() -> int:
    with cursor() as conn:
        rows = conn.execute(
            "SELECT r.id, r.title, r.status, r.duration_ms, r.model, "
            "  (SELECT COUNT(*) FROM transcript_segments s WHERE s.recording_id = r.id) AS segs, "
            "  (SELECT COUNT(DISTINCT speaker_label) FROM transcript_segments s "
            "   WHERE s.recording_id = r.id) AS speakers "
            "FROM recordings r ORDER BY r.id DESC").fetchall()
    if not rows:
        print("No recordings.")
        return 1
    print(f"{'id':>4}  {'status':<13} {'len':>8} {'segs':>5} {'spk':>4}  title")
    for r in rows:
        print(f"{r['id']:>4}  {r['status']:<13} {clock(r['duration_ms']):>8} "
              f"{r['segs']:>5} {r['speakers']:>4}  {r['title']}")
    print("\nPass an id to analyse it.")
    return 0


def analyse(recording_id: int, show_text: bool) -> int:
    with cursor() as conn:
        rec = conn.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)).fetchone()
        if rec is None:
            print(f"No recording {recording_id}.")
            return 1
        segs = [dict(s) for s in conn.execute(
            "SELECT idx, speaker_label, start_ms, end_ms, text FROM transcript_segments "
            "WHERE recording_id = ? ORDER BY idx", (recording_id,))]

    print(f"\n  {rec['title']}")
    print(f"  status {rec['status']}   model {rec['model'] or '?'}   "
          f"length {clock(rec['duration_ms'])}   {len(segs)} segments")
    if rec["note"]:
        print(f"  note: {rec['note']}")
    if not segs:
        print("\n  No transcript.")
        return 1

    # --- who speaks, in five minute buckets -------------------------------
    span = max((s["end_ms"] or s["start_ms"] or 0) for s in segs)
    buckets: dict[int, dict[str, int]] = {}
    for s in segs:
        b = (s["start_ms"] or 0) // (BUCKET_MIN * 60_000)
        buckets.setdefault(b, {}).setdefault(s["speaker_label"] or "?", 0)
        buckets[b][s["speaker_label"] or "?"] += 1

    labels = sorted({s["speaker_label"] or "?" for s in segs})
    print(f"\n  Speakers seen: {', '.join(labels)}")
    print(f"\n  {'window':<14} {'segs':>5}  distinct  distribution")
    print("  " + "-" * 62)

    collapse_at = None
    for b in range(0, span // (BUCKET_MIN * 60_000) + 1):
        counts = buckets.get(b, {})
        total = sum(counts.values())
        window = f"{b * BUCKET_MIN:>3}-{(b + 1) * BUCKET_MIN:<3} min"
        if not total:
            print(f"  {window:<14} {'0':>5}  {'-':>8}  (silence or no segments)")
            continue
        share = "  ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
        distinct = len(counts)
        flag = ""
        if distinct == 1 and total > 2:
            flag = "   <-- one voice only"
            if collapse_at is None and b > 0:
                collapse_at = b
        else:
            collapse_at = None          # it recovered; not a collapse
        print(f"  {window:<14} {total:>5}  {distinct:>8}  {share}{flag}")

    # --- the verdict -------------------------------------------------------
    print()
    if collapse_at is not None:
        minute = collapse_at * BUCKET_MIN
        print(f"  Attribution collapses to a single speaker from about {minute} minutes")
        print(f"  and does not recover. Everything after {minute:02d}:00 is one label.")
        if minute >= 25:
            print()
            print("  This is the documented platform limit, not a fault in the audio:")
            print("  diarization is supported up to thirty minutes of audio. Past that")
            print("  the model keeps emitting whichever label it used last.")
            print("  Fix: transcribe long recordings in windows. ENYGMA does this")
            print("  automatically when ffmpeg is available -- see chunking below.")
    else:
        print("  No sustained collapse: more than one speaker appears throughout.")

    # --- how many turns each label actually gets ---------------------------
    print(f"\n  {'speaker':<14} {'turns':>6} {'first':>8} {'last':>8}")
    print("  " + "-" * 42)
    for label in labels:
        mine = [s for s in segs if (s["speaker_label"] or "?") == label]
        print(f"  {label:<14} {len(mine):>6} {clock(mine[0]['start_ms']):>8} "
              f"{clock(mine[-1]['start_ms']):>8}")

    if show_text:
        print("\n  Turn changes:")
        last = None
        for s in segs:
            if s["speaker_label"] != last:
                print(f"    {clock(s['start_ms'])}  {s['speaker_label']:<12} "
                      f"{(s['text'] or '')[:64]}")
                last = s["speaker_label"]
    return 0


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        return listing()

    if not args[0].isdigit():
        # Placeholders in documentation get pasted literally, and a shell eats
        # angle brackets before this program ever sees them. Say what to do
        # instead of raising a traceback about it.
        print(f"'{args[0]}' is not a recording id. Here is the list; pass a")
        print("number from the first column.\n")
        return listing()

    return analyse(int(args[0]), "--text" in sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
