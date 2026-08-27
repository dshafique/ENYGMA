"""Splitting long audio so speaker attribution survives.

Diarization on this platform is supported up to thirty minutes of audio. Past
that the model stops distinguishing voices and keeps emitting whichever label it
used last -- so a fifty minute meeting comes back correctly attributed for half
an hour and then as one uninterrupted monologue. Nothing errors; the transcript
is simply wrong in a way that looks fine.

The fix is to transcribe in windows that stay inside the limit, and to stitch the
speaker labels back together afterwards. Each window is diarized independently,
so its SPEAKER 1 has nothing to do with the previous window's SPEAKER 1. The
windows therefore overlap, and the overlap is what makes the identities
recoverable: the same speech appears at the end of one window and the start of
the next, so matching that speech gives a mapping between the two label sets.

Requires ffmpeg. Without it, long audio is still transcribed -- just in one piece,
with a note saying attribution past the limit is not trustworthy.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import config


def have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def duration_ms(path: Path) -> int | None:
    """Length of the audio, before a word of it has been transcribed."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode != 0:
            return None
        return int(float(out.stdout.strip()) * 1000)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


@dataclass
class Window:
    index: int
    path: Path
    offset_ms: int          # where this window starts in the original recording
    length_ms: int


def plan(total_ms: int) -> list[tuple[int, int]]:
    """(offset, length) pairs covering the whole recording, with overlap.

    Windows are shorter than the limit rather than exactly at it, because a
    window that sits on the boundary is a window that sometimes crosses it.
    """
    window = config.CHUNK_MINUTES * 60_000
    overlap = config.CHUNK_OVERLAP_SECONDS * 1000
    if total_ms <= window:
        return [(0, total_ms)]

    out: list[tuple[int, int]] = []
    start = 0
    while start < total_ms:
        length = min(window, total_ms - start)
        out.append((start, length))
        if start + length >= total_ms:
            break
        start += window - overlap
    return out


def split(path: Path, total_ms: int, into: Path) -> list[Window]:
    """Cut the audio into overlapping windows. Copies the stream, never re-encodes."""
    windows: list[Window] = []
    suffix = path.suffix or ".mp3"
    for i, (offset, length) in enumerate(plan(total_ms)):
        target = into / f"w{i:03d}{suffix}"
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-ss", f"{offset / 1000:.3f}", "-t", f"{length / 1000:.3f}",
             "-i", str(path), "-c", "copy", str(target)],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            # Stream copy cannot always cut cleanly on a keyframe boundary.
            # Re-encoding is slower but always works.
            result = subprocess.run(
                ["ffmpeg", "-v", "error", "-y",
                 "-ss", f"{offset / 1000:.3f}", "-t", f"{length / 1000:.3f}",
                 "-i", str(path), str(target)],
                capture_output=True, text=True, timeout=1800,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg could not cut window {i} of {path.name}: "
                    f"{result.stderr.strip()[:200]}")
        windows.append(Window(i, target, offset, length))
    return windows


def workspace() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="enygma-chunks-")
