"""The Gemini backend.

Verified against the audio documentation on 22 Aug 2026:

* model            gemini-3.5-flash accepts audio through the Interactions API
* duration         up to 9.5 hours of audio per prompt
* inline threshold 20 MB total request size; above that the Files API is required
* formats          WAV, MP3, AIFF, AAC, OGG Vorbis, FLAC
* diarization      supported, but it has to be **asked for explicitly** and the
                   labels have to be checked. PHNTM got speakers from pyannote;
                   here they come out of a prompt, so they are a claim, not a fact.

Timestamps are requested in MM:SS and parsed back to milliseconds. If the model
returns something unparseable the segment still lands, with a null timestamp,
because a transcript without a clock is still a transcript.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import config
from .base import Backend, Segment, Transcript, Summary

TRANSCRIBE_PROMPT = """Transcribe this meeting recording in full.

Return JSON only, with this exact shape:
{"segments":[{"speaker":"SPEAKER 1","start":"MM:SS","end":"MM:SS","text":"..."}]}

Rules:
- Attribute every segment to a speaker. Label them SPEAKER 1, SPEAKER 2 and so on,
  in the order they first speak. Never guess a real name, even if one is said aloud.
- Keep the same label for the same voice throughout.
- Start a new segment whenever the speaker changes.
- Transcribe what was said, including false starts. Do not summarise or tidy.
- If a passage is inaudible, write [inaudible] rather than inventing words.
"""

SUMMARISE_PROMPT = """Here is a speaker-attributed transcript of a meeting.

Return JSON only, with this exact shape:
{"abstract":"...",
 "decisions":[{"text":"...","at":"MM:SS"}],
 "questions":[{"text":"...","at":"MM:SS"}],
 "actions":[{"text":"...","owner":"SPEAKER 2 or null","at":"MM:SS"}]}

Rules:
- The abstract is two or three sentences. No preamble, no "In this meeting".
- Every decision, question and action carries the timestamp it came from. If you
  cannot point at a moment, leave the item out.
- An action is something a person committed to do. Not a topic, not an idea.
- Owners are speaker labels, never invented names.
- Return empty arrays rather than inventing items.

TRANSCRIPT:
"""


def _ms(stamp: str | None) -> int | None:
    if not stamp:
        return None
    match = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", str(stamp).strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return ((int(hours or 0) * 3600) + int(minutes) * 60 + int(seconds)) * 1000


def _json_from(text: str) -> dict:
    """Models fence JSON in markdown more often than not."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The model did not return JSON")
    return json.loads(cleaned[start:end + 1])


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self, client=None):
        self._client = client
        self.model = config.GEMINI_MODEL

    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=config.gemini_key())
        return self._client

    def _ask(self, parts: list) -> str:
        client = self._get_client()
        interaction = client.interactions.create(model=self.model, input=parts)
        return interaction.output_text

    def transcribe(self, audio_path, mime: str) -> Transcript:
        path = Path(audio_path)
        client = self._get_client()
        size = path.stat().st_size

        if size > config.GEMINI_INLINE_LIMIT:
            uploaded = client.files.upload(file=str(path))
            audio_part = {"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type}
        else:
            audio_part = {"type": "audio", "data": path.read_bytes(), "mime_type": mime}

        raw = self._ask([{"type": "text", "text": TRANSCRIBE_PROMPT}, audio_part])
        payload = _json_from(raw)
        segments = [
            Segment(
                speaker_label=(row.get("speaker") or "SPEAKER 1").strip().upper(),
                start_ms=_ms(row.get("start")),
                end_ms=_ms(row.get("end")),
                text=(row.get("text") or "").strip(),
            )
            for row in payload.get("segments", [])
            if (row.get("text") or "").strip()
        ]
        if not segments:
            raise RuntimeError("Gemini returned no transcript segments")
        return Transcript(segments=segments, model=self.model)

    def summarise(self, transcript: Transcript) -> Summary:
        raw = self._ask([{"type": "text", "text": SUMMARISE_PROMPT + transcript.as_text()}])
        payload = _json_from(raw)
        pick = lambda rows: [
            {"text": r.get("text", "").strip(), "at_ms": _ms(r.get("at"))}
            for r in rows or [] if r.get("text")
        ]
        return Summary(
            abstract=(payload.get("abstract") or "").strip(),
            decisions=pick(payload.get("decisions")),
            questions=pick(payload.get("questions")),
            actions=[
                {"text": r.get("text", "").strip(),
                 "owner": (r.get("owner") or None),
                 "at_ms": _ms(r.get("at"))}
                for r in payload.get("actions") or [] if r.get("text")
            ],
            model=self.model,
        )


def get_backend() -> Backend:
    if config.PIPELINE == "gemini":
        return GeminiBackend()
    from .stub import StubBackend
    return StubBackend()
