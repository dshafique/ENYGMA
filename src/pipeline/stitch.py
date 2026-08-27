"""Making one transcript out of several independently diarized windows.

Every window is diarized on its own, so window 2's "SPEAKER 1" is not window 1's
"SPEAKER 1" -- the numbering restarts and means nothing across the boundary.
Joining them naively is how you get a transcript where a person changes identity
every twenty-five minutes, which is worse than the collapse it was meant to fix.

The windows overlap. The same speech is transcribed twice: once at the end of one
window and again at the start of the next. Matching that repeated speech gives a
mapping from the new window's labels to the ones already in use.

Matching is on the words, not on timing, because the two windows disagree about
what time it is: each one thinks it starts at zero, and the model's own
timestamps drift. Words are the thing both windows genuinely share.
"""
from __future__ import annotations

import re
from collections import Counter

from .base import Segment


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _shingles(text: str, size: int = 4) -> set[tuple[str, ...]]:
    """Overlapping runs of words. Robust to the two windows transcribing a
    passage slightly differently, which they will."""
    words = _words(text)
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def _similarity(a: str, b: str) -> float:
    left, right = _shingles(a), _shingles(b)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def map_labels(previous: list[Segment], incoming: list[Segment],
               overlap_start_ms: int, threshold: float = 0.34) -> dict[str, str]:
    """Which of `incoming`'s labels are which of `previous`'s.

    Both lists are in original-recording time. Only the overlapping region is
    considered, because that is the only place the two windows describe the same
    speech.
    """
    tail = [s for s in previous if (s.end_ms or 0) >= overlap_start_ms]
    head = [s for s in incoming if (s.start_ms or 0) < (previous[-1].end_ms or 0)] \
        if previous else []
    if not tail or not head:
        return {}

    # For each incoming segment, the old segment it most resembles. A speaker
    # match is a vote, not a decision: one confused line should not rename a
    # person, so the votes are counted per label pair.
    votes: Counter[tuple[str, str]] = Counter()
    for new in head:
        best_score, best_label = 0.0, None
        for old in tail:
            score = _similarity(new.text, old.text)
            if score > best_score:
                best_score, best_label = score, old.speaker_label
        if best_label and best_score >= threshold:
            votes[(new.speaker_label, best_label)] += 1

    mapping: dict[str, str] = {}
    claimed: set[str] = set()
    # Strongest evidence first, and one old label cannot be claimed twice:
    # two distinct voices in the new window must stay two distinct voices.
    for (new_label, old_label), _count in votes.most_common():
        if new_label in mapping or old_label in claimed:
            continue
        mapping[new_label] = old_label
        claimed.add(old_label)
    return mapping


def join(windows: list[tuple[int, list[Segment]]], overlap_ms: int) -> list[Segment]:
    """Splice windows into one transcript.

    windows is [(offset_ms, segments)], each segment's times already shifted into
    original-recording time. Overlapping speech is kept once, from the earlier
    window, because that window had more preceding context when it heard it.
    """
    if not windows:
        return []

    merged: list[Segment] = list(windows[0][1])
    next_free = 1
    seen: set[str] = {s.speaker_label for s in merged}

    for offset, segments in windows[1:]:
        if not segments:
            continue
        overlap_start = offset
        mapping = map_labels(merged, segments, overlap_start)

        # Any label the overlap did not explain is somebody the earlier window
        # never heard. Give them a new number rather than guessing.
        for segment in segments:
            if segment.speaker_label not in mapping:
                while True:
                    candidate = f"SPEAKER {len(seen) + next_free}"
                    if candidate not in seen:
                        break
                    next_free += 1
                mapping[segment.speaker_label] = candidate
                seen.add(candidate)

        boundary = merged[-1].end_ms or 0
        for segment in segments:
            if (segment.start_ms or 0) < boundary:
                continue                       # already covered by the earlier window
            merged.append(Segment(
                speaker_label=mapping.get(segment.speaker_label, segment.speaker_label),
                start_ms=segment.start_ms, end_ms=segment.end_ms, text=segment.text,
            ))
    return merged
