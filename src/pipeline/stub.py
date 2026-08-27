"""A backend that costs nothing and needs no network.

It exists so the whole app can be built, demonstrated and tested before the Gemini
bill starts, and so the tests never depend on a third party being up. It is
deterministic: the same file always produces the same transcript.
"""
import hashlib

from .base import Backend, Segment, Transcript, Summary

LINES = [
    ("SPEAKER 1", "They are pushing the sensor data over MQTT into the broker."),
    ("SPEAKER 2", "That works until the broker restarts. Last time the retained messages replayed."),
    ("SPEAKER 1", "Then we pin the versions and treat anything after that as a change request."),
    ("SPEAKER 2", "Agreed. I will send the revised scope tonight."),
    ("SPEAKER 3", "Can we confirm the integration window before Friday?"),
]


class StubBackend(Backend):
    name = "stub"

    def transcribe(self, audio_path, mime: str) -> Transcript:
        seed = int(hashlib.sha256(str(audio_path).encode()).hexdigest()[:8], 16)
        segments = []
        cursor_ms = (seed % 30) * 1000
        for i, (speaker, text) in enumerate(LINES):
            duration = 4000 + (seed >> i) % 6000
            segments.append(Segment(speaker, cursor_ms, cursor_ms + duration, text))
            cursor_ms += duration + 800
        return Transcript(segments=segments, model="stub")

    def summarise(self, transcript: Transcript) -> Summary:
        first = transcript.segments[0].start_ms if transcript.segments else 0
        return Summary(
            abstract=("A short working discussion about moving sensor data through a "
                      "broker, and what happens to retained messages when it restarts."),
            decisions=[{"text": "Pin the versions and treat later changes as change requests.",
                        "at_ms": first + 9000}],
            questions=[{"text": "Can the integration window be confirmed before Friday?",
                        "at_ms": first + 20000}],
            actions=[{"text": "Send the revised scope", "owner": "SPEAKER 2", "at_ms": first + 14000},
                     {"text": "Confirm the integration window", "owner": None, "at_ms": first + 20000}],
            model="stub",
        )
