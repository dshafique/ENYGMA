import os, sys, tempfile, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret-not-a-real-one")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")
os.environ.setdefault("ENYGMA_RP_ID", "localhost")
os.environ.setdefault("ENYGMA_ORIGIN", "http://localhost:4073")

from src import db, config as cfg          # noqa: E402
from src.auth import session, attempts, secrets_store, passkeys  # noqa: E402


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "test.db"
    cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH
    db.DATA_DIR = cfg.DATA_DIR
    import src.db as m
    m.DB_PATH = cfg.DB_PATH
    m.DATA_DIR = cfg.DATA_DIR
    db.migrate()


def test_migrations_are_idempotent():
    first = db.migrate()
    second = db.migrate()
    assert second == [], "re-running migrations must be a no-op"


def test_session_roundtrip_and_staleness():
    import time
    token = session.issue()
    state = session.read(token)
    assert state and state["fresh"] is True
    old = session.issue(verified_at=time.time() - 60 * 60)
    assert session.read(old)["fresh"] is False
    assert session.read("garbage") is None


def test_session_cookie_carries_no_domain():
    """__Host- forbids a Domain attribute, so the cookie cannot be scoped upward.

    Mutating the attribute rather than reloading the module on purpose: a reload
    rebinds config.config, and every module that did `from ..config import config`
    keeps the old object, so half the app silently reads stale settings.
    """
    from fastapi.responses import JSONResponse
    was = cfg.config.INSECURE_COOKIES
    cfg.config.INSECURE_COOKIES = False
    try:
        r = JSONResponse({})
        session.set_on(r, session.issue())
        header = r.headers["set-cookie"]
        assert header.startswith("__Host-enygma_session=")
        assert "domain=" not in header.lower()
        assert "secure" in header.lower() and "httponly" in header.lower()
    finally:
        cfg.config.INSECURE_COOKIES = was


def test_pin_is_hashed_and_verified():
    secrets_store.set_pin("481920")
    assert secrets_store.verify_pin("481920") is True
    assert secrets_store.verify_pin("000000") is False
    with db.cursor() as conn:
        row = conn.execute("SELECT hash FROM pin WHERE id = 1").fetchone()
    assert "481920" not in row["hash"], "the PIN must never be recoverable from storage"
    assert row["hash"].startswith("$argon2")


def test_recovery_codes_are_single_use():
    codes = secrets_store.generate_recovery_codes()
    assert len(codes) == 6 and all(len(c) == 4 for c in codes)
    assert not set("O0I1") & set("".join(codes)), "ambiguous characters must not appear"
    assert secrets_store.consume_recovery_code(codes[0]) is True
    assert secrets_store.consume_recovery_code(codes[0]) is False


def test_one_counter_for_both_methods():
    with db.cursor() as conn:
        conn.execute("DELETE FROM auth_attempts")
    for _ in range(3):
        attempts.record("passkey", False)
    for _ in range(2):
        attempts.record("pin", False)
    assert attempts.failures() == 5, "five total across both methods, not five each"
    assert attempts.lockout_remaining() > 0
    attempts.record("passkey", True)
    assert attempts.lockout_remaining() == 0, "a success clears the counter"


def test_challenge_is_single_use_and_scoped():
    token, _ = passkeys.registration_options()
    assert passkeys._take_challenge(token, "register") is not None
    assert passkeys._take_challenge(token, "register") is None, "challenges are single use"
    token2, _ = passkeys.registration_options()
    assert passkeys._take_challenge(token2, "authenticate") is None, "purpose must match"


def test_registration_options_request_a_discoverable_credential():
    import json
    _, options = passkeys.registration_options()
    payload = json.loads(options)
    sel = payload["authenticatorSelection"]
    assert sel["residentKey"] == "required", "this is what removes the login form"
    assert sel["userVerification"] == "required"
    assert payload["rp"]["id"] == cfg.config.RP_ID
