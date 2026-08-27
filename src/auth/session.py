"""Session cookie and the re-auth window.

__Host-enygma_session forbids a Domain attribute, so the cookie physically cannot be
scoped to arkhm.io. The isolation test in the handoff passes by construction rather
than by inspection.
"""
import time
from itsdangerous import TimestampSigner, BadSignature

from ..config import config

COOKIE_NAME = "__Host-enygma_session"
INSECURE_COOKIE_NAME = "enygma_session"  # local http development only
MAX_AGE = 60 * 60 * 24 * 30


def cookie_name() -> str:
    return INSECURE_COOKIE_NAME if config.INSECURE_COOKIES else COOKIE_NAME


def _signer() -> TimestampSigner:
    return TimestampSigner(config.session_secret(), salt="enygma-session")


def issue(verified_at: float | None = None) -> str:
    verified_at = verified_at or time.time()
    return _signer().sign(f"1|{int(verified_at)}").decode()


def read(raw: str | None) -> dict | None:
    """Returns {'fresh': bool} or None when the cookie is absent or invalid."""
    if not raw:
        return None
    try:
        value = _signer().unsign(raw, max_age=MAX_AGE).decode()
    except BadSignature:
        return None
    try:
        _, verified_at = value.split("|", 1)
        verified_at = int(verified_at)
    except (ValueError, TypeError):
        return None
    age_minutes = (time.time() - verified_at) / 60
    return {"verified_at": verified_at, "fresh": age_minutes < config.REAUTH_MINUTES}


def set_on(response, value: str) -> None:
    response.set_cookie(
        cookie_name(),
        value,
        max_age=MAX_AGE,
        httponly=True,
        secure=not config.INSECURE_COOKIES,
        samesite="lax",
        path="/",
        # No domain. That is the point of the __Host- prefix.
    )


def clear_on(response) -> None:
    response.delete_cookie(cookie_name(), path="/")
