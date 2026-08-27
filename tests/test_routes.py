"""HTTP level tests.

These exist because of a bug that shipped: the "/" route was still rendering the
skeleton placeholder instead of redirecting to the meetings list. Every other test
called /meetings directly, so nothing caught it. A route nobody requests in a test
is a route nobody has checked.
"""
import io, os, sys, pathlib, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from fastapi.testclient import TestClient        # noqa: E402
from src import db, config as cfg                # noqa: E402
from src.auth import session                     # noqa: E402
from src.ingest import upload                    # noqa: E402


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"; upload.BASE_DIR = tmp
    db.migrate()
    cfg.config.INSECURE_COOKIES = True


def client(signed_in: bool = False) -> TestClient:
    from src.main import app
    c = TestClient(app, follow_redirects=False)
    if signed_in:
        c.cookies.set(session.cookie_name(), session.issue())
    return c


def test_root_without_a_session_goes_to_the_lock_screen():
    r = client().get("/")
    assert r.status_code == 302
    assert r.headers["location"] == "/lock"


def test_root_with_a_session_is_the_home_screen():
    """The bug this file exists for: root used to render a placeholder. It is now
    a real page, so the assertion is that it renders Home, not that it redirects."""
    r = client(signed_in=True).get("/")
    assert r.status_code == 200
    assert "Good" in r.text and "Open actions" in r.text


def test_meetings_page_renders_the_dropzone():
    r = client(signed_in=True).get("/meetings")
    assert r.status_code == 200
    assert "Drop audio here" in r.text
    assert "Meetings" in r.text


def test_meetings_page_without_a_session_goes_to_the_lock_screen():
    r = client().get("/meetings")
    assert r.status_code == 302 and r.headers["location"] == "/lock"


def test_upload_requires_a_session():
    r = client().post("/upload", files={"files": ("x.mp3", b"ID3xxxx", "audio/mpeg")})
    assert r.status_code == 401


def test_upload_then_the_meeting_appears_in_the_list_and_the_api():
    c = client(signed_in=True)
    r = c.post("/upload", files={"files": ("Board meeting.mp3", b"ID3" + b"\x22" * 5000, "audio/mpeg")})
    assert r.status_code == 200
    assert r.json()["results"][0]["title"] == "Board meeting"

    listed = c.get("/api/meetings").json()["meetings"]
    assert any(m["title"] == "Board meeting" for m in listed)
    assert "Board meeting" in c.get("/meetings").text, "the list is rendered server side"

    page = c.get("/meetings/" + str(listed[0]["id"]))
    assert page.status_code == 200
    assert "Board meeting" in page.text


def test_a_missing_meeting_is_a_404_not_a_crash():
    assert client(signed_in=True).get("/meetings/999999").status_code == 404


def test_healthz_needs_no_session():
    r = client().get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_nothing_references_a_template_that_no_longer_exists():
    """The original bug was a route rendering a template nobody had looked at in
    weeks. Generalised: every template main.py names must be on disk."""
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    named = set(re.findall(r'"([a-z_]+\.html)"', (root / "src/main.py").read_text()))
    assert named, "no templates found — the pattern stopped matching"
    missing = [n for n in named if not (root / "src/templates" / n).exists()]
    assert not missing, f"main.py renders templates that do not exist: {missing}"
    assert not (root / "src/templates/meeting.html").exists(), \
        "meeting.html was folded into meetings.html; a stale copy will shadow it"
