"""Opus, for when the local model is not enough.

Deliberately the smallest possible client. This is the expensive path and the
one that leaves the building, so it should be reached for on purpose and be
obvious in the code when it has been.
"""
from __future__ import annotations

import base64
import json

import httpx

from ..config import config


class AnthropicError(RuntimeError):
    """Said in a sentence, like every other backend's failures."""


class AnthropicBackend:
    name = "opus"
    API = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str | None = None, api_key: str | None = None):
        self.model = model or config.ANTHROPIC_MODEL
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        # Recorded on the instance rather than returned, so callers that do not
        # care about the bill are not made to handle it.
        self.usage = {"input": 0, "output": 0}

    HEADERS_VERSION = "2023-06-01"

    def _body(self, parts: list, schema: dict | None = None) -> dict:
        """The request. Shared, so the streaming call and the blocking one
        cannot quietly ask for different things."""
        if not self.api_key:
            raise AnthropicError(
                "No Anthropic key is set. Put ENYGMA_ANTHROPIC_API_KEY in the "
                ".env and restart, or pick a different model for this thread.")

        content = []
        for part in parts:
            if part.get("type") == "image":
                content.append({"type": "image", "source": {
                    "type": "base64", "media_type": part.get("mime", "image/jpeg"),
                    "data": base64.b64encode(part["data"]).decode()}})
            elif part.get("text"):
                content.append({"type": "text", "text": part["text"]})

        body = {"model": self.model, "max_tokens": 4096,
                "messages": [{"role": "user", "content": content}]}
        if schema is not None:
            # No response_format on this API; asking plainly and parsing is what
            # the salvage path downstream already handles.
            body["messages"][0]["content"].append({
                "type": "text",
                "text": "Reply with JSON matching this schema and nothing else: "
                        f"{schema}"})
        return body

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key,
                "anthropic-version": self.HEADERS_VERSION,
                "content-type": "application/json"}

    def _refuse(self, status: int, text: str) -> None:
        if status == 401:
            raise AnthropicError("Anthropic rejected the key.")
        if status == 429:
            raise AnthropicError("Anthropic is rate limiting. Try again shortly, "
                                 "or switch this thread to Local.")
        if status >= 400:
            raise AnthropicError(f"Anthropic said {status}: {text[:200]}")

    def stream(self, parts: list, schema: dict | None = None):
        """The answer a piece at a time, over server-sent events.

        Usage is recorded as it arrives rather than at the end, so an answer he
        stops halfway is still billed for what it actually cost. Anthropic has
        already generated those tokens whether or not he reads them, and a
        stopped answer that shows up as free would make the running total on
        Home quietly wrong in the direction that matters.
        """
        body = dict(self._body(parts, schema), stream=True)
        self.usage = {"input": 0, "output": 0}
        try:
            with httpx.Client(timeout=300.0) as client:
                with client.stream("POST", self.API, json=body,
                                   headers=self._headers()) as response:
                    if response.status_code >= 400:
                        response.read()
                        self._refuse(response.status_code, response.text)
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        kind = event.get("type")
                        if kind == "content_block_delta":
                            piece = (event.get("delta") or {}).get("text") or ""
                            if piece:
                                yield piece
                        elif kind == "message_start":
                            usage = ((event.get("message") or {}).get("usage") or {})
                            self.usage["input"] = usage.get("input_tokens", 0)
                        elif kind == "message_delta":
                            usage = event.get("usage") or {}
                            if usage.get("output_tokens"):
                                self.usage["output"] = usage["output_tokens"]
                        elif kind == "error":
                            said = (event.get("error") or {}).get("message", "")
                            raise AnthropicError(f"Anthropic stopped: {said[:200]}")
        except httpx.HTTPError as exc:
            raise AnthropicError(f"Could not reach Anthropic: {exc}") from exc

    def _ask(self, parts: list, schema: dict | None = None) -> str:
        body = self._body(parts, schema)
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(self.API, json=body,
                                       headers=self._headers())
        except httpx.HTTPError as exc:
            raise AnthropicError(f"Could not reach Anthropic: {exc}") from exc

        self._refuse(response.status_code, response.text)

        payload = response.json()
        usage = payload.get("usage") or {}
        self.usage = {"input": usage.get("input_tokens", 0),
                      "output": usage.get("output_tokens", 0)}
        return "".join(block.get("text", "")
                       for block in payload.get("content", [])).strip()
