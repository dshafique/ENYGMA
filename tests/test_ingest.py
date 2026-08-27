"""The poller's job is to make two facts distinguishable. These tests exist mostly
to prove that a dead token can never be mistaken for an empty account."""
import json, os, sys, pathlib, tempfile
import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_HINOTES_BASE", "https://hinotes.test")
os.environ.setdefault("ENYGMA_HINOTES_TOKEN", "tok_do_not_log_me")

from src import db, config as cfg                       # noqa: E402
from src.ingest.hinotes import HiNotes, CredentialsExpired, HiNotesUnavailable  # noqa: E402
from src.ingest import poller                           # noqa: E402

TOKEN = "tok_do_not_log_me"
DEAD = {"error": 10000, "message": "session_timeout", "data": None}


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    for module in (cfg, db, poller):
        pass
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    poller.UPLOADS = tmp / "uploads"
    db.migrate()


def clean():
    with db.cursor() as conn:
        conn.execute("DELETE FROM recordings")
        conn.execute("DELETE FROM ingest_log")


def client_for(handler):
    return HiNotes(token=TOKEN, base="https://hinotes.test",
                   transport=httpx.MockTransport(handler))


def listing(rows):
    def handler(request):
        assert request.headers.get("Accesstoken") == TOKEN, "header name is exact"
        assert TOKEN not in str(request.url), "the token never goes in a URL"
        if request.url.path == "/v1/note/recording/list":
            return httpx.Response(200, json={"error": 0, "data": rows})
        if request.url.path == "/v2/note/audio/download":
            return httpx.Response(200, content=b"ID3fake-mp3-bytes",
                                  headers={"content-type": "audio/mpeg"})
        return httpx.Response(404)
    return handler


# ---------------------------------------------------------------- the trap
def test_dead_token_returns_200_and_is_still_detected():
    """The whole reason this module exists."""
    def handler(request):
        return httpx.Response(200, json=DEAD)      # 200, not 401
    with client_for(handler) as c:
        with pytest.raises(CredentialsExpired):
            c.list_recordings()


def test_dead_token_is_not_reported_as_nothing_new():
    clean()
    def handler(request):
        return httpx.Response(200, json=DEAD)
    result = poller.pull_once(client_for(handler))
    assert result["outcome"] == "credentials_expired"
    assert result["outcome"] != "nothing_new"
    st = poller.status()
    assert st["credentials_ok"] is False


def test_empty_account_is_nothing_new_not_expired():
    clean()
    result = poller.pull_once(client_for(listing([])))
    assert result["outcome"] == "nothing_new"
    assert poller.status()["credentials_ok"] is True


def test_the_two_outcomes_are_distinguishable_in_the_log():
    clean()
    poller.pull_once(client_for(listing([])))
    poller.pull_once(client_for(lambda r: httpx.Response(200, json=DEAD)))
    outcomes = [row["outcome"] for row in poller.status()["log"]]
    assert "nothing_new" in outcomes and "credentials_expired" in outcomes
    assert len(set(outcomes)) == 2, "they must never collapse into one outcome"


# ---------------------------------------------------------------- pulling
def test_pull_stores_audio_and_is_idempotent():
    clean()
    rows = [{"noteId": "n1", "noteTitle": "Quarterly review.hda",
             "createTime": "2026-08-21 10:30:00", "duration": 2537}]
    first = poller.pull_once(client_for(listing(rows)))
    assert first == {"outcome": "pulled", "count": 1, "detail": None}
    second = poller.pull_once(client_for(listing(rows)))
    assert second["outcome"] == "nothing_new", "a second pass must not re-ingest"
    with db.cursor() as conn:
        recs = list(conn.execute("SELECT * FROM recordings"))
    assert len(recs) == 1
    assert recs[0]["title"] == "Quarterly review", ".hda is stripped from the title"
    assert recs[0]["audio_path"].endswith(".mp3"), "the server transcodes to MP3"
    assert recs[0]["bytes"] == len(b"ID3fake-mp3-bytes")
    assert recs[0]["duration_ms"] == 2537000, "seconds are normalised to ms"


def test_alternative_key_spellings_are_accepted():
    clean()
    rows = [{"id": "n9", "title": "Standup", "createtime": "2026-08-20 09:00:00"}]
    assert poller.pull_once(client_for(listing(rows)))["outcome"] == "pulled"


def test_server_error_is_retryable_not_a_credential_problem():
    clean()
    result = poller.pull_once(client_for(lambda r: httpx.Response(503)))
    assert result["outcome"] == "error"
    assert poller.status()["credentials_ok"] is True, "a 503 must not look like expiry"


def test_the_token_never_reaches_the_log():
    clean()
    poller.pull_once(client_for(lambda r: httpx.Response(200, json=DEAD)))
    poller.pull_once(client_for(lambda r: httpx.Response(503)))
    blob = json.dumps(poller.status())
    assert TOKEN not in blob
    with db.cursor() as conn:
        rows = list(conn.execute("SELECT detail FROM ingest_log WHERE detail IS NOT NULL"))
    assert all(TOKEN not in (r["detail"] or "") for r in rows)


def test_audio_endpoint_returning_the_envelope_is_caught():
    """A dead token can surface at download time as a 200 carrying JSON."""
    def handler(request):
        if request.url.path.endswith("/list"):
            return httpx.Response(200, json={"error": 0, "data": [
                {"noteId": "n2", "noteTitle": "Vendor call", "createTime": "2026-08-21 16:05:00"}]})
        return httpx.Response(200, json=DEAD, headers={"content-type": "application/json"})
    clean()
    result = poller.pull_once(client_for(handler))
    assert result["outcome"] == "credentials_expired"
