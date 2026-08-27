"""HiNotes client.

The contract below is verified and was learned the hard way. Two things about it
matter more than the rest.

**A dead token returns HTTP 200.** Not 401. The body is
``{"error": 10000, "message": "session_timeout", "data": null}``. Detecting expiry
by status code makes a dead token look like an empty account, and the poller then
reports clean runs forever while ingesting nothing. **The envelope check is the real
credential gate.** Never replace it with a status check.

**The .hda extension in note titles is a red herring.** The server transcodes to MP3
on the way out, so what lands on disk is an MP3 whatever the title says.
"""
from __future__ import annotations

import httpx

from ..config import config

LIST_PATH = "/v1/note/recording/list"
DOWNLOAD_PATH = "/v2/note/audio/download"

# The header is Accesstoken: capital A, the rest lowercase. Not Access-Token,
# not Authorization.
TOKEN_HEADER = "Accesstoken"

SESSION_TIMEOUT_ERROR = 10000


class CredentialsExpired(RuntimeError):
    """The token is dead. Distinct from 'the account is empty' on purpose."""


class HiNotesUnavailable(RuntimeError):
    """Network, timeout or 5xx. Retryable; not a credential problem."""


def _check_envelope(payload: dict) -> dict:
    """The real credential gate. Runs on every response, including 200s."""
    if not isinstance(payload, dict):
        raise HiNotesUnavailable("Unexpected response shape")
    error = payload.get("error")
    if error == SESSION_TIMEOUT_ERROR or payload.get("message") == "session_timeout":
        raise CredentialsExpired("The recorder token has expired.")
    if error not in (None, 0):
        # Never echo the body: it can carry identifiers.
        raise HiNotesUnavailable(f"HiNotes returned error {error}")
    return payload


class HiNotes:
    def __init__(self, token: str | None = None, base: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self._token = token or config.hinotes_token()
        self._base = (base or config.HINOTES_BASE).rstrip("/")
        if not self._base:
            raise RuntimeError(
                "ENYGMA_HINOTES_BASE is not set. Lift it from PHNTM's hinotes module."
            )
        self._client = httpx.Client(
            base_url=self._base,
            timeout=config.HINOTES_TIMEOUT,
            # The token goes in a header, never in a URL, never in a log line.
            headers={TOKEN_HEADER: self._token},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    def _get(self, path: str, params: dict) -> httpx.Response:
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise HiNotesUnavailable(f"{type(exc).__name__} reaching HiNotes") from None
        if response.status_code >= 500:
            raise HiNotesUnavailable(f"HiNotes returned {response.status_code}")
        return response

    def list_recordings(self, page_index: int = 0, page_size: int | None = None) -> list[dict]:
        response = self._get(LIST_PATH, {
            "pageSize": page_size or config.HINOTES_PAGE_SIZE,
            "pageIndex": page_index,
            "sortField": "createtime",
        })
        try:
            payload = response.json()
        except ValueError:
            raise HiNotesUnavailable("HiNotes did not return JSON") from None
        data = _check_envelope(payload).get("data")
        if data is None:
            return []
        if isinstance(data, dict):
            data = data.get("list") or data.get("records") or []
        return list(data)

    def download_audio(self, note_id: str) -> bytes:
        response = self._get(DOWNLOAD_PATH, {"noteId": note_id})
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            # A dead token can surface here too, as a 200 carrying the envelope
            # instead of audio. Same gate.
            try:
                _check_envelope(response.json())
            except ValueError:
                raise HiNotesUnavailable("HiNotes returned neither audio nor JSON") from None
            raise HiNotesUnavailable("HiNotes returned no audio for that note")
        if not response.content:
            raise HiNotesUnavailable("HiNotes returned an empty body")
        return response.content
