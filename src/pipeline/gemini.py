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

import base64
import json
import re
from pathlib import Path

from ..config import config
from ..grounding import NEVER_INVENT


def _grounded(prompt: str) -> str:
    """Put the shared truthfulness clause into a prompt.

    Substituted rather than interpolated: every prompt here is mostly a JSON
    shape, and an f-string would try to read those braces as format fields.
    """
    return prompt.replace("<<GROUNDING>>", NEVER_INVENT)
from .base import Backend, Segment, Transcript, Summary
from . import chunking, stitch

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

<<GROUNDING>>
"""

SUMMARISE_PROMPT = """Here is a speaker-attributed transcript of a meeting.

Return JSON only, with this exact shape:
{"abstract":"...",
 "topics":[{"heading":"...","text":"..."}],
 "decisions":[{"text":"...","at":"MM:SS or null"}],
 "questions":[{"text":"...","at":"MM:SS or null"}],
 "actions":[{"text":"...","owner":"SPEAKER 2 or null","at":"MM:SS or null"}]}

He was in this meeting and is catching up on it afterwards, or proving to
himself he did not miss anything. Completeness matters more than brevity.

The abstract:
- Two or three sentences. No preamble, no "In this meeting".

Topics:
- Walk the meeting in order and give each subject its own entry.
- The heading is a short noun phrase naming the subject. The text is two to four
  sentences on what was actually said about it: who raised it, what was
  concluded, what was left hanging.
- A forty minute meeting usually has eight to fifteen of these. Do not compress
  several subjects into one entry to be brief.

Actions:
- Anything anyone committed to doing. A commitment by the group counts and is
  common: "the team will bring the metadata question to Thursday" is an action,
  and dropping it because no single person said "I will" loses half the meeting.
- Say who, when someone owns it. Use the speaker label, never an invented name.
  Where the group owns it, leave the owner null and say "The team will ..." in
  the text.
- One action per commitment. Do not merge two into a sentence with "and".

Decisions are things settled. Questions are things left open.

Timestamps:
- Give the timestamp where you can point at a moment.
- Where a commitment or a conclusion built up over a stretch of talk and there
  is no one moment, use null. DO NOT drop the item. A missing timestamp is a
  smaller loss than a missing action, and this rule used to be the other way
  round, which quietly deleted about half of every meeting.

<<GROUNDING>>

An empty array is right when nothing of that kind happened, but "I could not
timestamp it" is not the same as "it did not happen".

TRANSCRIPT:
"""


NOTES_PROMPT = """These are notes from a meeting. Nobody recorded it, so there is
no audio and no transcript: this is all there is.

Return JSON only, with this exact shape:
{"title":"...",
 "date":"YYYY-MM-DD or null",
 "attendees":["Full Name", ...],
 "abstract":"...",
 "decisions":[{"text":"..."}],
 "questions":[{"text":"..."}],
 "actions":[{"text":"...","owner":"Full Name or null"}]}

Rules:
- Take the title, the date and the attendees from the notes if they are stated.
  Do not infer a date from anything other than a date written down. Use null
  rather than guessing.
- Attendees are the people named as present or invited. Do not invent anyone,
  and do not turn a company name into a person.
- The abstract is two or three sentences. No preamble.
- A decision is something that was settled. A question is something left open.
  An action is something a named person committed to do.
- Do NOT include timestamps. There is no recording to point at, and a timestamp
  here would be a fabrication.
- Use only what the notes say. If the notes do not cover something, leave the
  array empty rather than filling it in from what is likely.

<<GROUNDING>>

NOTES:
"""

NOTES_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "attendees": {"type": "array", "items": {"type": "string"}},
        "abstract": {"type": "string"},
        "decisions": {"type": "array", "items": {
            "type": "object", "properties": {"text": {"type": "string"}},
            "required": ["text"]}},
        "questions": {"type": "array", "items": {
            "type": "object", "properties": {"text": {"type": "string"}},
            "required": ["text"]}},
        "actions": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "owner": {"type": "string"}},
            "required": ["text"]}},
    },
    "required": ["title", "abstract", "decisions", "questions", "actions"],
}


def _ms(stamp: str | None) -> int | None:
    if not stamp:
        return None
    match = re.match(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$", str(stamp).strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return ((int(hours or 0) * 3600) + int(minutes) * 60 + int(seconds)) * 1000


# The shape the model is *constrained* to produce. Schema-guided decoding means
# malformed JSON is not a thing that can come back; only truncation can, and the
# salvage parser below handles that.
TRANSCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "speaker": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["speaker", "start", "end", "text"],
            },
        }
    },
    "required": ["segments"],
}

TRANSCRIBE_PROMPT = _grounded(TRANSCRIBE_PROMPT)
SUMMARISE_PROMPT = _grounded(SUMMARISE_PROMPT)
NOTES_PROMPT = _grounded(NOTES_PROMPT)


_ITEM = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "at": {"type": "string"}},
    # "at" is deliberately not required. It used to be, which made an item the
    # model could not place structurally invalid rather than merely untimed --
    # so the schema was deleting real material and the prompt was telling it to.
    "required": ["text"],
}
_TOPIC = {
    "type": "object",
    "properties": {"heading": {"type": "string"}, "text": {"type": "string"}},
    "required": ["heading", "text"],
}
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "abstract": {"type": "string"},
        "topics": {"type": "array", "items": _TOPIC},
        "decisions": {"type": "array", "items": _ITEM},
        "questions": {"type": "array", "items": _ITEM},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "owner": {"type": "string"},
                    "at": {"type": "string"},
                },
                "required": ["text"],
            },
        },
    },
    "required": ["abstract", "decisions", "questions", "actions"],
}

# Errors that mean "the request shape was wrong", as opposed to "the request was
# fine and something else failed". Only the first kind is worth retrying.
_SHAPE_ERROR = re.compile(
    r"invalid_request|unexpected keyword|unknown field|must be set|400",
    re.I,
)


def _unfence(text: str) -> str:
    """Models fence JSON in markdown more often than not."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.S)
    return cleaned.strip()


def _json_from(text: str) -> dict:
    cleaned = _unfence(text)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The model did not return JSON")
    return json.loads(cleaned[start:end + 1])


def _objects_in(text: str) -> list[dict]:
    """Every complete {...} object in the text, in order.

    A transcript arrives as one JSON document, and a document that is cut off --
    by an output ceiling, or a dropped chunk -- fails to parse in its entirety.
    An hour of correctly transcribed speech is then thrown away because of the
    last four characters. This walks the text and keeps every object that closes,
    so truncation costs the tail rather than the meeting.
    """
    out: list[dict] = []
    stack: list[int] = []          # start index of every object still open
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            # Objects at every depth, not just the outermost: the segments live
            # inside {"segments": [...]}, and it is the outer object that never
            # closes when the response is cut off.
            try:
                out.append(json.loads(text[start:i + 1]))
            except json.JSONDecodeError:
                pass
    return out


def segments_from(raw: str) -> tuple[list[dict], bool]:
    """(rows, salvaged). Strict parse first; recover what is there if it fails."""
    cleaned = _unfence(raw)
    try:
        payload = json.loads(cleaned)
        rows = payload.get("segments") if isinstance(payload, dict) else payload
        if isinstance(rows, list):
            return rows, False
    except json.JSONDecodeError:
        pass
    rows = [o for o in _objects_in(cleaned) if "text" in o and "speaker" in o]
    return rows, True


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self, client=None):
        self._client = client
        self.model = config.GEMINI_MODEL
        # Set when the constrained request was refused and the plain one was used.
        self.degraded: str | None = None
        # What the last call reported using. Zero until one has been made, so a
        # caller asking before then bills nothing rather than crashing.
        self.usage: dict = {"input": 0, "output": 0}

    def _get_client(self):
        if self._client is None:
            try:
                from google import genai
            except ImportError as exc:
                # "cannot import name 'genai' from 'google'" tells the operator
                # nothing about what to do next. This does.
                raise RuntimeError(
                    "The Gemini SDK is not installed, so ENYGMA_PIPELINE=gemini "
                    "cannot work. Install it with:  .venv/bin/pip install -r "
                    "requirements.txt  then restart. "
                    f"(underlying: {exc})"
                ) from exc
            self._client = genai.Client(api_key=config.gemini_key())
        return self._client

    def _ask(self, parts: list, schema: dict | None = None) -> str:
        """One call, with the constraints if they are accepted and without if not.

        A schema makes malformed JSON impossible; the raised ceiling makes
        truncation unlikely. Both are optional extras on the request, and an API
        that rejects an extra must not cost a transcription -- especially not one
        where the audio has already been uploaded. So: try the constrained
        request, and on a rejection that is specifically about the request's
        shape, fall back to the minimum request that is known to work.
        """
        client = self._get_client()
        minimum = {"model": self.model, "input": parts}
        request = dict(minimum,
                       generation_config={"max_output_tokens": config.MAX_OUTPUT_TOKENS})
        if schema is not None:
            request["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": schema,
            }
        try:
            response = client.interactions.create(**request)
        except Exception as exc:
            if not _SHAPE_ERROR.search(str(exc)):
                raise
            self.degraded = f"{type(exc).__name__}: {exc}"[:200]
            response = client.interactions.create(**minimum)
        self.usage = _usage_of(response)
        return response.output_text

    def transcribe(self, audio_path, mime: str) -> Transcript:
        """Whole, or in windows if the recording outruns the diarization limit."""
        path = Path(audio_path)
        total = chunking.duration_ms(path)
        limit = config.CHUNK_MINUTES * 60_000

        if total is None or total <= limit or not chunking.have_ffmpeg():
            transcript = self._transcribe_one(path, mime)
            extra = None
            if total is None:
                # The dangerous case: with no duration there is no way to know
                # whether this recording needed splitting, so it was not split.
                # Saying nothing here is how a half-wrong transcript looks right.
                extra = (
                    "The length of this recording could not be measured, because "
                    "ffprobe is not installed, so it was transcribed in one piece. "
                    f"If it runs past {config.CHUNK_MINUTES} minutes, speaker "
                    "attribution after that point is not trustworthy and the "
                    "transcript may thin out. Install ffmpeg and run it again."
                )
            elif total > limit and not chunking.have_ffmpeg():
                extra = (
                    f"This recording is {total // 60000} minutes long. Speaker "
                    f"attribution is only reliable for the first {config.CHUNK_MINUTES}, "
                    "and ffmpeg is not installed on this host so it could not be "
                    "split. Install ffmpeg and run it again for correct speakers "
                    "throughout."
                )
            transcript.note = " ".join(x for x in (transcript.note, extra) if x) or None
            return transcript

        return self._transcribe_windowed(path, mime, total)

    def _transcribe_windowed(self, path: Path, mime: str, total: int) -> Transcript:
        pieces: list[tuple[int, list[Segment]]] = []
        model = self.model
        with chunking.workspace() as tmp:
            windows = chunking.split(path, total, Path(tmp))
            for window in windows:
                part = self._transcribe_one(window.path, mime)
                model = part.model or model
                # Each window thinks it starts at zero. Move it to real time.
                shifted = [
                    Segment(
                        speaker_label=s.speaker_label,
                        start_ms=None if s.start_ms is None else s.start_ms + window.offset_ms,
                        end_ms=None if s.end_ms is None else s.end_ms + window.offset_ms,
                        text=s.text,
                    )
                    for s in part.segments
                ]
                pieces.append((window.offset_ms, shifted))

        segments = stitch.join(pieces, config.CHUNK_OVERLAP_SECONDS * 1000)
        if not segments:
            raise RuntimeError("No window of this recording produced any transcript.")
        speakers = len({s.speaker_label for s in segments})
        return Transcript(
            segments=segments,
            model=model,
            note=(f"Transcribed in {len(pieces)} overlapping windows, because "
                  f"speaker attribution is only supported up to "
                  f"{config.CHUNK_MINUTES} minutes at a time. {speakers} distinct "
                  "speakers were carried across the joins; check the names once."),
        )

    def _transcribe_one(self, audio_path, mime: str) -> Transcript:
        path = Path(audio_path)
        client = self._get_client()
        size = path.stat().st_size

        if size > config.GEMINI_INLINE_LIMIT:
            uploaded = client.files.upload(file=str(path))
            audio_part = {"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type}
        else:
            # Inline audio is base64 text, not raw bytes. Sending bytes fails at
            # the transport, not at the model, so the error does not mention audio.
            audio_part = {
                "type": "audio",
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "mime_type": mime,
            }

        raw = self._ask([{"type": "text", "text": TRANSCRIBE_PROMPT}, audio_part],
                        schema=TRANSCRIPT_SCHEMA)
        rows, salvaged = segments_from(raw)
        segments = [
            Segment(
                speaker_label=(row.get("speaker") or "SPEAKER 1").strip().upper(),
                start_ms=_ms(row.get("start")),
                end_ms=_ms(row.get("end")),
                text=(row.get("text") or "").strip(),
            )
            for row in rows
            if (row.get("text") or "").strip()
        ]
        if not segments:
            raise RuntimeError(
                "Gemini returned nothing that could be read as transcript segments. "
                f"The response began: {raw[:180]!r}"
            )
        note = None
        if salvaged:
            last = segments[-1].end_ms
            note = (f"The model's response was cut off. {len(segments)} segments were "
                    f"recovered, up to {(last or 0) // 60000}:{((last or 0) // 1000) % 60:02d}. "
                    "Re-run this meeting to try for the whole thing.")
        return Transcript(segments=segments, model=self.model, note=note)

    def digest_notes(self, text: str) -> dict:
        """Read a set of notes. No timestamps, because there is nothing to point at."""
        raw = self._ask([{"type": "text", "text": NOTES_PROMPT + text}],
                        schema=NOTES_SCHEMA)
        try:
            payload = _json_from(raw)
        except (ValueError, json.JSONDecodeError):
            found = _objects_in(_unfence(raw))
            payload = next((o for o in found if "abstract" in o), None) or {}
        payload["_model"] = self.model
        return _digest_from(payload)

    def summarise(self, transcript: Transcript) -> Summary:
        # Swapped for this one call only. See config.GEMINI_SUMMARY_MODEL for
        # why the cheap job is the one allowed the better model.
        was, self.model = self.model, config.GEMINI_SUMMARY_MODEL
        try:
            raw = self._ask(
                [{"type": "text", "text": SUMMARISE_PROMPT + transcript.as_text()}],
                schema=SUMMARY_SCHEMA)
        finally:
            self.model = was
        try:
            payload = _json_from(raw)
        except (ValueError, json.JSONDecodeError):
            # Same exposure as the transcript: one long document, and a cut-off
            # ending throws all of it away. Recover the pieces that closed.
            found = _objects_in(_unfence(raw))
            payload = next((o for o in found if "abstract" in o), None) or {}
            if not payload:
                payload = {
                    "decisions": [o for o in found if "text" in o and "at" in o],
                }
        pick = lambda rows: [
            {"text": r.get("text", "").strip(), "at_ms": _ms(r.get("at"))}
            for r in rows or [] if r.get("text")
        ]
        return Summary(
            abstract=(payload.get("abstract") or "").strip(),
            topics=[{"heading": (r.get("heading") or "").strip(),
                     "text": (r.get("text") or "").strip()}
                    for r in payload.get("topics") or []
                    if (r.get("heading") or "").strip() and (r.get("text") or "").strip()],
            decisions=pick(payload.get("decisions")),
            questions=pick(payload.get("questions")),
            actions=[
                {"text": r.get("text", "").strip(),
                 "owner": (r.get("owner") or None),
                 "at_ms": _ms(r.get("at"))}
                for r in payload.get("actions") or [] if r.get("text")
            ],
            model=config.GEMINI_SUMMARY_MODEL,
        )


def _digest_from(payload: dict) -> dict:
    """The model's reading of a set of notes, with nothing invented added."""
    def items(rows):
        return [{"text": (r.get("text") or "").strip(), "at_ms": None}
                for r in rows or [] if (r.get("text") or "").strip()]

    date = (payload.get("date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        date = None                      # a date that is not a date is not a date

    return {
        "title": (payload.get("title") or "").strip(),
        "date": date,
        "attendees": [a.strip() for a in payload.get("attendees") or []
                      if isinstance(a, str) and a.strip()][:24],
        "summary": Summary(
            abstract=(payload.get("abstract") or "").strip(),
            decisions=items(payload.get("decisions")),
            questions=items(payload.get("questions")),
            actions=[{"text": (r.get("text") or "").strip(),
                      "owner": (r.get("owner") or None), "at_ms": None}
                     for r in payload.get("actions") or [] if (r.get("text") or "").strip()],
            model=payload.get("_model", ""),
        ),
    }


def get_backend() -> Backend:
    if config.PIPELINE == "gemini":
        return GeminiBackend()
    from .stub import StubBackend
    return StubBackend()


def _usage_of(response) -> dict:
    """Tokens, if the response says. Best effort on purpose.

    The field has moved between versions of this SDK and it is not worth a hard
    dependency: an uncounted call leaves the running total a little low, which
    is honest, while a crash here would cost a transcription that already
    happened and already cost money.
    """
    for name in ("usage_metadata", "usage"):
        block = getattr(response, name, None)
        if block is None:
            continue
        got = {}
        for key, names in (
            ("input", ("prompt_token_count", "input_tokens", "input_token_count")),
            ("output", ("candidates_token_count", "output_tokens",
                        "output_token_count")),
        ):
            for attribute in names:
                value = getattr(block, attribute, None)
                if isinstance(value, int):
                    got[key] = value
                    break
        if got:
            return {"input": got.get("input", 0), "output": got.get("output", 0)}
    return {"input": 0, "output": 0}
