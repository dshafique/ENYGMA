"""WebAuthn registration and authentication.

residentKey=required is the option the whole lock screen design rests on. A
discoverable credential lets the authenticator say who the user is without being
told, so authentication runs with an empty allowCredentials and the lock screen
needs no email field, no username field and no "remember me". Drop this option and
the lock screen grows a text field.
"""
import base64
import secrets
import uuid

from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
    options_to_json,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
    AttestationConveyancePreference,
)

from ..config import config
from ..db import cursor

CHALLENGE_TTL_MINUTES = 5


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _store_challenge(challenge: bytes, purpose: str) -> str:
    token = uuid.uuid4().hex
    with cursor() as conn:
        conn.execute(
            "INSERT INTO challenges (id, challenge, purpose, expires_at) "
            "VALUES (?, ?, ?, datetime('now', ?))",
            (token, challenge, purpose, f"+{CHALLENGE_TTL_MINUTES} minutes"),
        )
    return token


def _take_challenge(token: str, purpose: str) -> bytes | None:
    """Single use. Consuming and expiry are both enforced here, not by the caller."""
    with cursor() as conn:
        row = conn.execute(
            "SELECT challenge FROM challenges WHERE id = ? AND purpose = ? "
            "AND consumed_at IS NULL AND expires_at > datetime('now')",
            (token, purpose),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE challenges SET consumed_at = datetime('now') WHERE id = ?", (token,)
        )
    return row["challenge"]


def registration_options() -> tuple[str, str]:
    opts = generate_registration_options(
        rp_id=config.RP_ID,
        rp_name=config.RP_NAME,
        user_id=b"enygma-operator-1",
        user_name="yahya",
        user_display_name="Yahya",
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    token = _store_challenge(opts.challenge, "register")
    return token, options_to_json(opts)


def verify_registration(token: str, credential: dict, device_name: str) -> None:
    challenge = _take_challenge(token, "register")
    if challenge is None:
        raise ValueError("That challenge has expired. Start again.")
    result = verify_registration_response(
        credential=credential,
        expected_challenge=challenge,
        expected_origin=config.ORIGIN,
        expected_rp_id=config.RP_ID,
        require_user_verification=True,
    )
    with cursor() as conn:
        conn.execute(
            "INSERT INTO credentials (credential_id, public_key, sign_count, device_name) "
            "VALUES (?, ?, ?, ?)",
            (result.credential_id, result.credential_public_key, result.sign_count,
             device_name.strip() or "Unnamed device"),
        )


def authentication_options() -> tuple[str, str]:
    opts = generate_authentication_options(
        rp_id=config.RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
        # Empty on purpose: the credential is discoverable.
        allow_credentials=[],
    )
    token = _store_challenge(opts.challenge, "authenticate")
    return token, options_to_json(opts)


def verify_authentication(token: str, credential: dict) -> None:
    challenge = _take_challenge(token, "authenticate")
    if challenge is None:
        raise ValueError("That challenge has expired. Start again.")

    raw_id = base64.urlsafe_b64decode(credential["rawId"] + "==")
    with cursor() as conn:
        row = conn.execute(
            "SELECT id, public_key, sign_count FROM credentials "
            "WHERE credential_id = ? AND revoked_at IS NULL",
            (raw_id,),
        ).fetchone()
    if not row:
        raise ValueError("This device is not enrolled.")

    result = verify_authentication_response(
        credential=credential,
        expected_challenge=challenge,
        expected_origin=config.ORIGIN,
        expected_rp_id=config.RP_ID,
        credential_public_key=row["public_key"],
        credential_current_sign_count=row["sign_count"],
        require_user_verification=True,
    )

    # Only enforce the counter when the authenticator actually keeps one. Most
    # platform authenticators, including a Samsung side key, report zero forever,
    # and enforcing against them locks the operator out of his own phone.
    stored = row["sign_count"]
    if stored > 0 and result.new_sign_count <= stored:
        with cursor() as conn:
            conn.execute(
                "UPDATE credentials SET revoked_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        raise ValueError("This credential looks cloned and has been revoked.")

    with cursor() as conn:
        conn.execute(
            "UPDATE credentials SET sign_count = ?, last_used_at = datetime('now') "
            "WHERE id = ?",
            (result.new_sign_count, row["id"]),
        )


def enrolled_devices() -> list[dict]:
    with cursor() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, device_name, created_at, last_used_at FROM credentials "
                "WHERE revoked_at IS NULL ORDER BY created_at"
            )
        ]


def has_any_credential() -> bool:
    with cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM credentials WHERE revoked_at IS NULL"
        ).fetchone()
        return row["n"] > 0
