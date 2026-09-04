"""The local model, on the Spark, over ollama.

The reason this exists is not the bill, though it helps. It is that everything
ENYGMA does other than transcribe audio can now happen on a machine in his
brother's flat: the questions he asks about his employer's work, the photographs
he takes at the bench, the documents he writes from them. Only the meeting audio
still has to leave the building, because ollama has no audio model and
diarization is not something a text model can be talked into.

Deliberately not a transcription backend. This class answers questions and reads
images; `Backend.transcribe` stays Gemini's job, and pretending otherwise would
produce a plausible transcript with invented speakers, which is worse than no
transcript at all.
"""
from __future__ import annotations

import base64
import json
import pathlib

import httpx

from ..config import config


class OllamaError(RuntimeError):
    """Said in a sentence he can act on, because the fix is usually local:
    ollama is not running, or the model has not been pulled."""


class OllamaBackend:
    name = "local"

    def __init__(self, model: str | None = None, host: str | None = None):
        self.model = model or config.OLLAMA_MODEL
        self.host = (host or config.OLLAMA_HOST).rstrip("/")

    # The same shape GeminiBackend exposes, so chat.py and documents.py do not
    # need to know which one they are holding.
    def _ask(self, parts: list, schema: dict | None = None) -> str:
        text = "\n\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
        images = [p["data"] for p in parts if p.get("type") == "image"]
        return self.ask(text, images=images, schema=schema)

    def ask(self, prompt: str, images: list[bytes] | None = None,
            schema: dict | None = None, timeout: float | None = None) -> str:
        message: dict = {"role": "user", "content": prompt}
        if images:
            # ollama wants base64 without a data: prefix.
            message["images"] = [base64.b64encode(raw).decode() for raw in images]

        request: dict = {
            "model": self.model,
            "messages": [message],
            "stream": False,
            "options": {"num_ctx": config.OLLAMA_CONTEXT},
        }
        if schema is not None:
            # ollama constrains generation to a JSON schema the same way the
            # hosted APIs do, so the salvage parser downstream stays unused.
            request["format"] = schema

        try:
            with httpx.Client(timeout=timeout or config.OLLAMA_TIMEOUT) as client:
                response = client.post(f"{self.host}/api/chat", json=request)
        except httpx.ConnectError as exc:
            raise OllamaError(
                f"Nothing is answering at {self.host}. On the host: "
                "systemctl status ollama") from exc
        except httpx.ReadTimeout as exc:
            raise OllamaError(
                f"{self.model} took longer than {config.OLLAMA_TIMEOUT:.0f}s. A big "
                "model on a cold start can; try once more, or pick a smaller one "
                "in Settings.") from exc

        if response.status_code == 404:
            raise OllamaError(
                f"{self.model} is not pulled on this machine. "
                f"On the host: ollama pull {self.model}")
        if response.status_code >= 400:
            raise OllamaError(f"ollama said {response.status_code}: "
                              f"{response.text[:200]}")

        body = response.json()
        content = (body.get("message") or {}).get("content") or ""
        return _without_thinking(content).strip()

    def stream(self, parts: list, schema: dict | None = None):
        """The same answer, a piece at a time.

        Yields text as it arrives. The caller can stop reading at any point and
        the connection is closed under it, which is what the stop button in Chat
        actually does -- there is no cancel API to call, closing the socket is
        the cancel.
        """
        text = "\n\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
        images = [p["data"] for p in parts if p.get("type") == "image"]
        message: dict = {"role": "user", "content": text}
        if images:
            message["images"] = [base64.b64encode(raw).decode() for raw in images]

        request: dict = {
            "model": self.model,
            "messages": [message],
            "stream": True,
            "options": {"num_ctx": config.OLLAMA_CONTEXT},
        }
        if schema is not None:
            request["format"] = schema

        filter_ = Unthink()
        try:
            with httpx.Client(timeout=config.OLLAMA_TIMEOUT) as client:
                with client.stream("POST", f"{self.host}/api/chat",
                                   json=request) as response:
                    if response.status_code == 404:
                        raise OllamaError(
                            f"{self.model} is not pulled on this machine. "
                            f"On the host: ollama pull {self.model}")
                    if response.status_code >= 400:
                        response.read()
                        raise OllamaError(f"ollama said {response.status_code}: "
                                          f"{response.text[:200]}")
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        try:
                            body = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        piece = (body.get("message") or {}).get("content") or ""
                        if piece:
                            shown = filter_.feed(piece)
                            if shown:
                                yield shown
                        if body.get("done"):
                            break
        except httpx.ConnectError as exc:
            raise OllamaError(
                f"Nothing is answering at {self.host}. On the host: "
                "systemctl status ollama") from exc
        except httpx.ReadTimeout as exc:
            raise OllamaError(
                f"{self.model} stopped sending. A big model on a cold start "
                "can take a while; try once more, or pick a smaller one in "
                "Settings.") from exc
        rest = filter_.close()
        if rest:
            yield rest

    def available(self) -> tuple[bool, str]:
        """Whether this can be relied on right now, and why not if not.

        Asked before a thread is allowed to sit on the local model, so he finds
        out that ollama is down when he opens the picker rather than after he
        has typed a paragraph into it.
        """
        try:
            with httpx.Client(timeout=4.0) as client:
                tags = client.get(f"{self.host}/api/tags")
            if tags.status_code >= 400:
                return False, f"ollama answered {tags.status_code}"
            names = {m.get("name", "") for m in tags.json().get("models", [])}
            if self.model not in names:
                return False, (f"{self.model} is not pulled. Available: "
                               + ", ".join(sorted(names)[:4]))
            return True, ""
        except Exception as exc:
            return False, f"cannot reach ollama at {self.host}: {type(exc).__name__}"

    def models(self) -> list[dict]:
        """What is on the machine, so Settings lists reality rather than a
        hard-coded guess that goes stale the moment he pulls something."""
        try:
            with httpx.Client(timeout=4.0) as client:
                tags = client.get(f"{self.host}/api/tags")
            tags.raise_for_status()
        except Exception:
            return []
        out = []
        for m in tags.json().get("models", []):
            details = m.get("details") or {}
            out.append({
                "name": m.get("name", ""),
                "size": m.get("size", 0),
                "parameters": details.get("parameter_size", ""),
                "vision": "vision" in (m.get("capabilities") or []),
            })
        return sorted(out, key=lambda m: m["name"])


# Several of these models emit their reasoning before the answer. It is
# interesting and it is not what he asked for, so it is taken off the front.
_THINK_TAGS = ("think", "thinking", "reasoning")


class Unthink:
    """Strip reasoning blocks out of a stream, without waiting for the end.

    `_without_thinking` below can see the whole answer before it decides. A
    stream cannot: it has to decide about "<thi" before knowing whether "nk>" is
    coming. So anything at the tail that could still turn into a tag is held
    back and released once it turns out not to be one, and everything between an
    opening tag and its closing tag is dropped on the floor.

    The unclosed case is the one that matters. A model that is cut off mid-
    thought -- which is exactly what the stop button does -- has emitted an
    opening tag and no closing one, and every character after it is reasoning.
    So `close()` throws the held text away rather than flushing it, and a
    stopped answer that never got past thinking is empty rather than a paragraph
    of the model talking to itself.
    """

    OPEN = tuple(f"<{tag}>" for tag in _THINK_TAGS)
    SHUT = tuple(f"</{tag}>" for tag in _THINK_TAGS)

    def __init__(self):
        self.held = ""
        self.inside = False

    def feed(self, chunk: str) -> str:
        self.held += chunk or ""
        out = []
        while True:
            wanted = self.SHUT if self.inside else self.OPEN
            at, tag = _first_of(self.held, wanted)
            if at is not None:
                if not self.inside:
                    out.append(self.held[:at])
                self.held = self.held[at + len(tag):]
                self.inside = not self.inside
                continue
            # No whole tag. Keep back only what could still become one.
            keep = _partial_tail(self.held, wanted)
            if not self.inside:
                out.append(self.held[:len(self.held) - keep])
            self.held = self.held[len(self.held) - keep:]
            break
        return "".join(out)

    def close(self) -> str:
        """Whatever is left. Nothing, if the model was still thinking."""
        rest = "" if self.inside else self.held
        self.held = ""
        return rest


def _first_of(text: str, tags) -> tuple[int | None, str]:
    best, found = None, ""
    for tag in tags:
        at = text.find(tag)
        if at != -1 and (best is None or at < best):
            best, found = at, tag
    return best, found


def _partial_tail(text: str, tags) -> int:
    """How many characters at the end could still grow into one of these tags."""
    longest = max(len(tag) for tag in tags)
    for size in range(min(longest - 1, len(text)), 0, -1):
        tail = text[-size:]
        if any(tag.startswith(tail) for tag in tags):
            return size
    return 0


def _without_thinking(text: str) -> str:
    out = text
    for tag in _THINK_TAGS:
        opening, closing = f"<{tag}>", f"</{tag}>"
        while opening in out and closing in out:
            start = out.index(opening)
            end = out.index(closing, start) + len(closing)
            out = out[:start] + out[end:]
        # An unclosed block means the model was cut off mid-thought. Everything
        # after the opening tag is reasoning, so none of it is the answer.
        if opening in out:
            out = out[:out.index(opening)]
    return out
