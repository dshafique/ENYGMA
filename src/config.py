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

    REAUTH_MINUTES = int(os.environ.get("ENYGMA_REAUTH_MINUTES", "5"))
    INSECURE_COOKIES = os.environ.get("ENYGMA_INSECURE_COOKIES", "0") == "1"

    # Five failures across passkey and PIN combined, then thirty seconds.
    MAX_ATTEMPTS = 5
    LOCKOUT_SECONDS = 30

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
    WORKER_POLL_SECONDS = float(os.environ.get("ENYGMA_WORKER_POLL_SECONDS", "3"))

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
    def session_secret() -> str:
        return _require("ENYGMA_SESSION_SECRET")


config = Config()
