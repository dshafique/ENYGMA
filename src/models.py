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


def offered() -> list[dict]:
    """What the picker shows, with anything unusable marked and said why.

    He should find out that ollama is down when he opens the picker, not after
    he has typed a paragraph into a thread that cannot answer.
    """
    out = []
    for key, label, note, vision in CHOICES:
        ready, why = True, ""
        if key == "local":
            from .pipeline.ollama import OllamaBackend
            ready, why = OllamaBackend().available()
        elif key == "gemini":
            ready = config.has("ENYGMA_GEMINI_API_KEY")
            why = "" if ready else "no key set"
        elif key == "opus":
            ready = config.has("ENYGMA_ANTHROPIC_API_KEY")
            why = "" if ready else "no key set"
        out.append({"key": key, "label": label, "note": note,
                    "vision": vision, "ready": ready, "why": why})
    return out
