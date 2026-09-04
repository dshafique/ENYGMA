"""Which model answers, and what that costs him in privacy.

Three choices, and the difference that matters is not quality. It is where the
words go. Local never leaves the Spark. Gemini and Opus do. The interface says
so next to the picker, every time, because that is the only place the question
is ever put in front of him and he is asking about his employer's work.

Chosen per thread rather than per message: Chat has memory, and half a
conversation reasoned by one model and half by another is a conversation neither
of them is really having.
"""
from __future__ import annotations

import time

from .config import config

# order, key, label, the note shown beside the picker, whether it can see images
CHOICES = (
    ("local",  "Local",  "Never leaves the Spark", True),
    ("gemini", "Gemini", "Google reads it",        True),
    ("opus",   "Opus",   "Anthropic reads it",     True),
)
KEYS = tuple(key for key, _, _, _ in CHOICES)
LABELS = {key: label for key, label, _, _ in CHOICES}
NOTES = {key: note for key, _, note, _ in CHOICES}


def default() -> str:
    wanted = (config.CHAT_DEFAULT or "local").lower()
    return wanted if wanted in KEYS else "local"


def resolve(name: str | None) -> str:
    """A thread's stored choice, or the current default if it never made one."""
    name = (name or "").lower()
    return name if name in KEYS else default()


def backend_for(name: str | None):
    """The thing with an `_ask` on it. Raises with a sentence he can act on."""
    choice = resolve(name)
    if choice == "local":
        from .pipeline.ollama import OllamaBackend
        return OllamaBackend()
    if choice == "opus":
        from .pipeline.anthropic import AnthropicBackend
        return AnthropicBackend()
    from .pipeline.gemini import GeminiBackend
    return GeminiBackend()


# Whether the local model can answer is a network call, and `offered()` runs on
# every chat page render. Uncached, a stopped ollama turned every page load into
# a four second wait -- the test suite went from eight seconds to twenty, which
# is how this was noticed. Ten seconds is long enough to spare the round trip
# and short enough that starting ollama shows up almost at once.
_READY_FOR = 10.0
_ready_cache: dict = {}


def _local_ready() -> tuple[bool, str]:
    now = time.monotonic()
    cached = _ready_cache.get("local")
    if cached and now - cached[0] < _READY_FOR:
        return cached[1], cached[2]
    from .pipeline.ollama import OllamaBackend
    ready, why = OllamaBackend().available()
    _ready_cache["local"] = (now, ready, why)
    return ready, why


def forget_readiness() -> None:
    """For a test, or for the moment after he is told ollama is down."""
    _ready_cache.clear()


def offered() -> list[dict]:
    """What the picker shows, with anything unusable marked and said why.

    He should find out that ollama is down when he opens the picker, not after
    he has typed a paragraph into a thread that cannot answer.
    """
    out = []
    for key, label, note, vision in CHOICES:
        ready, why = True, ""
        if key == "local":
            ready, why = _local_ready()
        elif key == "gemini":
            ready = config.has("ENYGMA_GEMINI_API_KEY")
            why = "" if ready else "no key set"
        elif key == "opus":
            ready = config.has("ENYGMA_ANTHROPIC_API_KEY")
            why = "" if ready else "no key set"
        out.append({"key": key, "label": label, "note": note,
                    "vision": vision, "ready": ready, "why": why})
    return out
