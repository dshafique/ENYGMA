"""Opus, for when the local model is not enough.

Deliberately the smallest possible client. This is the expensive path and the
one that leaves the building, so it should be reached for on purpose and be
obvious in the code when it has been.
"""
from __future__ import annotations

import base64

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

    def _ask(self, parts: list, schema: dict | None = None) -> str:
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

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(self.API, json=body, headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"})
        except httpx.HTTPError as exc:
            raise AnthropicError(f"Could not reach Anthropic: {exc}") from exc

        if response.status_code == 401:
            raise AnthropicError("Anthropic rejected the key.")
        if response.status_code == 429:
            raise AnthropicError("Anthropic is rate limiting. Try again shortly, "
                                 "or switch this thread to Local.")
        if response.status_code >= 400:
            raise AnthropicError(f"Anthropic said {response.status_code}: "
                                 f"{response.text[:200]}")

        payload = response.json()
        usage = payload.get("usage") or {}
        self.usage = {"input": usage.get("input_tokens", 0),
                      "output": usage.get("output_tokens", 0)}
        return "".join(block.get("text", "")
                       for block in payload.get("content", [])).strip()
