"""What a transcription backend must return.

Segments are the unit. A summary that cannot point back at a segment is an
assertion the operator cannot check, so every claim carries a timestamp.
"""
from dataclasses import dataclass, field


@dataclass
class Segment:
    speaker_label: str
    start_ms: int | None
    end_ms: int | None
    text: str


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    model: str = ""

    @property
    def speaker_labels(self) -> list[str]:
        seen = []
        for s in self.segments:
            if s.speaker_label and s.speaker_label not in seen:
                seen.append(s.speaker_label)
        return seen

    def as_text(self) -> str:
        return "\n".join(
            f"[{(s.start_ms or 0)//60000:02d}:{((s.start_ms or 0)//1000)%60:02d}] "
            f"{s.speaker_label}: {s.text}"
            for s in self.segments
        )


@dataclass
class Summary:
    abstract: str = ""
    decisions: list[dict] = field(default_factory=list)   # {text, at_ms}
    questions: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)     # {text, owner, at_ms}
    model: str = ""


class Backend:
    name = "base"

    def transcribe(self, audio_path, mime: str) -> Transcript:
        raise NotImplementedError

    def summarise(self, transcript: Transcript) -> Summary:
        raise NotImplementedError
