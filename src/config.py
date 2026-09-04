"""Configuration. Every value comes from the environment; nothing is hardcoded.

BASE_DIR derives from this file's own location and the database path is relative to
it, so a second checkout isolates its paths for free.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "enygma.db"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def _stamp(name: str, fallback: str) -> str:
    """Which build is actually running.

    Added after an install silently re-deployed a stale extraction: the run looked
    completely healthy and was three days behind. A build stamp on /healthz turns
    that from a puzzle into a glance.

    Both files are written by tools/stamp_release.py and are not in version
    control, because their contents are derived from the commit that produced them.
    """
    try:
        return (BASE_DIR / name).read_text().strip() or fallback
    except OSError:
        return fallback


class Config:
    VERSION = _stamp("VERSION", "unknown")
    MARK = _stamp("MARK", "Mk II.dev")
    PORT = int(os.environ.get("ENYGMA_PORT", "4073"))
    HOST = os.environ.get("ENYGMA_HOST", "127.0.0.1")

    RP_ID = os.environ.get("ENYGMA_RP_ID", "enygma.arkhm.io")
    RP_NAME = os.environ.get("ENYGMA_RP_NAME", "ENYGMA")
    ORIGIN = os.environ.get("ENYGMA_ORIGIN", "https://enygma.arkhm.io")

    # Minutes before a state-changing request needs the passkey again. Five was
    # chosen when there was no way to re-authenticate without locking the whole
    # app; now that the sheet exists and keeps his place, thirty is the humane
    # number and still bounds the unattended-device window.
    # Timestamps are stored UTC and shown local. Defaults to the machine's own
    # zone, which on a home server is the operator's. Override if they differ.
    TZ = os.environ.get("ENYGMA_TZ", "").strip()

    REAUTH_MINUTES = int(os.environ.get("ENYGMA_REAUTH_MINUTES", "30"))
    INSECURE_COOKIES = os.environ.get("ENYGMA_INSECURE_COOKIES", "0") == "1"

    # Five failures across passkey and PIN combined, then thirty seconds, then
    # double for every further round. A short PIN is only safe behind a delay
    # that grows.
    MAX_ATTEMPTS = 5
    LOCKOUT_SECONDS = 30
    LOCKOUT_MAX_SECONDS = 60 * 60

    # Digits. Six is the default; four is allowed because a memorable PIN that
    # gets used beats a long one written on a sticky note, and the backoff above
    # is what actually carries the weight.
    PIN_MIN_DIGITS = 4
    PIN_MAX_DIGITS = 10

    # Modules are gated in config, never deleted. The HiNotes poller is off:
    # audio arrives by drag and drop. Turning it back on is one line.
    HINOTES_ENABLED = os.environ.get("ENYGMA_HINOTES_ENABLED", "0") == "1"

    # Uploads. Gemini accepts WAV, MP3, AIFF, AAC, OGG Vorbis and FLAC.
    MAX_UPLOAD_MB = int(os.environ.get("ENYGMA_MAX_UPLOAD_MB", "500"))
    ALLOWED_AUDIO = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
        ".aiff": "audio/aiff", ".aif": "audio/aiff",
    }

    # Pipeline. "stub" runs the whole app with no API key and no network, which is
    # how the interface gets built before the Gemini bill starts.
    PIPELINE = os.environ.get("ENYGMA_PIPELINE", "stub")
    GEMINI_MODEL = os.environ.get("ENYGMA_GEMINI_MODEL", "gemini-3.5-flash")
    # 20 MB is the documented inline threshold; above it the Files API is required.
    GEMINI_INLINE_LIMIT = 20 * 1024 * 1024
    # A long meeting is a long transcript. The default ceiling is low enough that
    # an hour of speech gets cut off mid-token, which fails as a JSON error and
    # looks like the model malfunctioning.
    MAX_OUTPUT_TOKENS = int(os.environ.get("ENYGMA_MAX_OUTPUT_TOKENS", "65536"))

    # Diarization is supported up to thirty minutes of audio. Past that the model
    # stops distinguishing voices and keeps using whichever label it had last, so
    # anything longer is transcribed in overlapping windows and stitched back
    # together. Twenty-five leaves room rather than sitting on the boundary.
    CHUNK_MINUTES = int(os.environ.get("ENYGMA_CHUNK_MINUTES", "25"))
    CHUNK_OVERLAP_SECONDS = int(os.environ.get("ENYGMA_CHUNK_OVERLAP_SECONDS", "90"))
    WORKER_POLL_SECONDS = float(os.environ.get("ENYGMA_WORKER_POLL_SECONDS", "3"))

    # Friday, local, on a 24-hour clock. Mid-afternoon rather than end of day:
    # the note is meant to be read and edited before he leaves, not found on
    # Monday morning describing a week he has stopped thinking about.
    WEEKNOTE_HOUR = int(os.environ.get("ENYGMA_WEEKNOTE_HOUR", "15"))

    # The local model, on the same machine. Chat, images and documents default
    # here: it is free, it is fast enough, and nothing he types leaves the
    # building. Transcription is not on this list, because ollama has no audio
    # model and a text model asked to transcribe will invent a plausible
    # meeting, which is worse than no meeting.
    OLLAMA_HOST = os.environ.get("ENYGMA_OLLAMA_HOST", "http://127.0.0.1:11434")
    OLLAMA_MODEL = os.environ.get("ENYGMA_OLLAMA_MODEL", "qwen3.6:35b")
    # These models carry very long contexts, but the whole context is memory the
    # host has to find. 32k is more than a chat thread with a library extract in
    # it ever needs.
    OLLAMA_CONTEXT = int(os.environ.get("ENYGMA_OLLAMA_CONTEXT", "32768"))
    # A 35B model on a cold start can take a while to answer the first question
    # after a reboot. Better a long wait than a failure he has to retype into.
    OLLAMA_TIMEOUT = float(os.environ.get("ENYGMA_OLLAMA_TIMEOUT", "180"))

    # Which model a new chat thread starts on.
    CHAT_DEFAULT = os.environ.get("ENYGMA_CHAT_DEFAULT", "local")
    # Say something every time the month's paid spend passes another round
    # number. Zero turns it off. He cannot see the bill until it arrives, and by
    # then it is spent.
    SPEND_STEP_DOLLARS = int(os.environ.get("ENYGMA_SPEND_STEP_DOLLARS", "10"))
    ANTHROPIC_API_KEY = os.environ.get("ENYGMA_ANTHROPIC_API_KEY", "").strip()
    ANTHROPIC_MODEL = os.environ.get("ENYGMA_ANTHROPIC_MODEL", "claude-opus-4-5")

    # HiNotes. The base URL is not in the handoff; lift it from PHNTM's
    # src/hinotes/ module rather than guessing, and confirm before first pull.
    HINOTES_BASE = os.environ.get("ENYGMA_HINOTES_BASE", "").rstrip("/")
    HINOTES_PAGE_SIZE = int(os.environ.get("ENYGMA_HINOTES_PAGE_SIZE", "50"))
    HINOTES_TIMEOUT = float(os.environ.get("ENYGMA_HINOTES_TIMEOUT", "30"))

    @staticmethod
    def hinotes_token() -> str:
        return _require("ENYGMA_HINOTES_TOKEN")

    @staticmethod
    def gemini_key() -> str:
        return _require("ENYGMA_GEMINI_API_KEY")

    @staticmethod
    def has(name: str) -> bool:
        """Whether a secret is set, without demanding it.

        The key methods raise, which is right at the point of use: a missing key
        should stop the call loudly rather than half-work. But the model picker
        has to ask "could this answer?" about all three before he has chosen
        any, and a question is not a use.
        """
        return bool(os.environ.get(name, "").strip())

    @staticmethod
    def session_secret() -> str:
        return _require("ENYGMA_SESSION_SECRET")


config = Config()
