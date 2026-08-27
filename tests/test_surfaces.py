"""Every tab, every empty state, and the two flows that cross between them.

Written after shipping a shell with only two screens in it: a page that no test
requests is a page nobody has looked at.
"""
import os, sys, pathlib, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from fastapi.testclient import TestClient        # noqa: E402
from src import db, config as cfg                # noqa: E402
from src.auth import session                     # noqa: E402
from src.ingest import upload                    # noqa: E402

PAGES = ["/", "/meetings", "/chat", "/actions", "/directory", "/settings"]


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"; upload.BASE_DIR = tmp
    db.migrate()
    cfg.config.INSECURE_COOKIES = True
    from src import glossary
    glossary.seed_if_empty()


def client(signed_in: bool = True) -> TestClient:
    from src.main import app
    c = TestClient(app, follow_redirects=False)
    if signed_in:
        c.cookies.set(session.cookie_name(), session.issue())
    return c


def test_every_tab_renders_on_an_empty_install():
    """The empty state is the first thing he will see. It has to be a page, not a
    stack trace."""
    c = client()
    for path in PAGES:
        r = c.get(path)
        assert r.status_code == 200, f"{path} returned {r.status_code}"
        assert "<nav class=\"rail\"" in r.text, f"{path} lost the shell"


def test_every_tab_redirects_to_the_lock_screen_without_a_session():
    c = client(signed_in=False)
    for path in PAGES:
        r = c.get(path)
        assert r.status_code == 302 and r.headers["location"] == "/lock", path


def test_the_nav_marks_the_current_destination_in_every_nav_that_holds_it():
    c = client()
    # The five tabs appear in the rail and in the handset tab bar.
    for path in ["/", "/meetings", "/chat", "/actions", "/directory"]:
        assert c.get(path).text.count('aria-current="page"') == 2, path
    # Settings is not a tab. It appears in the rail and in the handset header.
    assert c.get("/settings").text.count('aria-current="page"') == 2


def test_settings_and_the_theme_switch_are_reachable_without_the_rail():
    """The rail is hidden below 900px. Everything that lives only in the rail is
    unreachable on the Fold, which is the device he actually uses."""
    body = client().get("/").text
    bar = body[body.index('class="mobilebar"'):body.index('<main class="main">')]
    assert 'href="/settings"' in bar
    assert 'id="theme-m"' in bar


def test_the_glossary_answers_a_known_term_and_admits_an_unknown_one():
    c = client()
    known = c.get("/api/term?q=MQTT").json()
    assert known["known"] is True and "publish" in known["gloss"]
    unknown = c.get("/api/term?q=flibbertigibbet").json()
    assert unknown["known"] is False and unknown["gloss"] == ""


def test_learn_more_opens_a_thread_with_the_question_already_asked():
    c = client()
    res = c.post("/chat/from-term", json={"term": "Node-RED"})
    assert res.status_code == 200
    thread_id = res.json()["thread_id"]
    page = c.get(f"/chat/{thread_id}")
    assert page.status_code == 200
    assert "What is Node-RED?" in page.text
    assert "flow editor" in page.text, "the reply should carry the real glossary text"


def test_chat_says_it_cannot_reach_a_model_rather_than_inventing_one():
    c = client()
    thread_id = c.post("/chat/from-term", json={"term": "Broker"}).json()["thread_id"]
    assert "cannot reach a model" in c.get(f"/chat/{thread_id}").text


def test_the_caveat_is_said_once_not_on_every_turn():
    c = client()
    thread_id = c.post("/chat/from-term", json={"term": "Firmware"}).json()["thread_id"]
    c.post(f"/chat/{thread_id}/say", data={"body": "What is diarization?"})
    page = c.get(f"/chat/{thread_id}").text
    # Count inside the conversation only: the thread list shows previews of other
    # threads, and those carry the same sentence.
    convo = page[page.index('id="convo"'):page.index('class="composer"')]
    assert convo.count("cannot reach a model") == 1


def test_a_missing_thread_is_a_404_page_not_a_crash():
    r = client().get("/chat/999999", headers={"accept": "text/html"})
    assert r.status_code == 404
    assert "<nav class=\"rail\"" in r.text, "404 should still be a page in the shell"


def test_an_api_client_still_gets_json_not_html():
    r = client().get("/chat/999999", headers={"accept": "application/json"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_the_demo_week_populates_every_surface_and_comes_out_again():
    import importlib
    seed = importlib.import_module("tools.seed_demo")
    assert seed.seed() == 5
    c = client()
    assert "Quarterly review with Meridian" in c.get("/meetings").text
    assert "Priya Raman" in c.get("/directory").text
    assert "revised proposal" in c.get("/actions").text
    assert "Quarterly review with Meridian" in c.get("/").text
    assert seed.clear() == 5
    assert "Quarterly review with Meridian" not in c.get("/meetings").text
    assert "Priya Raman" not in c.get("/directory").text


def test_healthz_reports_the_build_so_a_stale_deploy_is_visible():
    """A stale install looked exactly like a correct one. It reported healthy and
    was three days behind. The build stamp is what makes that a glance."""
    body = client(signed_in=False).get("/healthz").json()
    assert body["version"] != "unknown", "VERSION file missing from the release"
    assert body["version"] in client().get("/settings").text


def test_every_static_asset_is_addressed_by_build():
    """A browser that cached the previous stylesheet served it against new markup:
    icons have no width in the old file, so each one expanded to fill the page.
    Version the URL and that cannot happen again."""
    import re
    from src.config import config
    page = client().get("/").text
    assets = re.findall(r'(?:href|src)="(/static/[^"]+)"', page)
    assert assets, "no static assets found — the pattern stopped matching"
    for url in assets:
        assert f"?v={config.VERSION}" in url, f"{url} is not addressed by build"


def test_an_icon_carries_its_own_size_without_any_stylesheet():
    """Defence in depth. CSS is an enhancement here, not load-bearing."""
    page = client().get("/").text
    assert page.count('<svg class="ico" width="20" height="20"') >= 10


def test_clearing_the_demo_week_leaves_real_uploads_alone():
    """The seeder marks its rows source='demo'. Anything he actually uploaded is
    source='upload' and must survive, along with everything hanging off it."""
    import importlib
    from src.db import cursor
    seed = importlib.import_module("tools.seed_demo")
    seed.seed()
    with cursor() as conn:
        conn.execute("INSERT INTO recordings (title, status, source, sha256) "
                     "VALUES ('A real meeting', 'ready', 'upload', 'realsha')")
        rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute("INSERT INTO action_items (recording_id, text) VALUES (?, 'real')", (rid,))

    assert seed.clear() == 5
    with cursor() as conn:
        rows = [dict(r) for r in conn.execute("SELECT title, source FROM recordings")]
        actions = conn.execute("SELECT COUNT(*) AS n FROM action_items").fetchone()["n"]
        orphans = conn.execute(
            "SELECT COUNT(*) AS n FROM transcript_segments s "
            "LEFT JOIN recordings r ON r.id = s.recording_id WHERE r.id IS NULL"
        ).fetchone()["n"]
    assert rows == [{"title": "A real meeting", "source": "upload"}]
    assert actions == 1
    assert orphans == 0, "clearing left transcript rows with no recording"


def test_run_sh_parses_dotenv_rather_than_executing_it():
    """A pasted command block landed inside .env instead of in the shell. If
    run.sh sourced that file, those lines would execute as the app user on every
    start -- and under systemd, on every restart."""
    import subprocess, tempfile, textwrap
    root = pathlib.Path(__file__).resolve().parent.parent
    run_sh = (root / "run.sh").read_text()
    assert ". ./.env" not in run_sh, "run.sh must not source .env"

    work = pathlib.Path(tempfile.mkdtemp())
    proof = work / "PROOF_OF_EXECUTION"
    (work / ".env").write_text(textwrap.dedent(f"""\
        ENYGMA_PORT=4099
        ENYGMA_SESSION_SECRET="quoted-value"
        # a comment
        sudo systemctl restart enygma
        touch {proof}
        """))
    # Replace the exec line so the probe stops before starting a server.
    body = run_sh[:run_sh.index('exec "$PY"')]
    body += 'echo "PORT=$ENYGMA_PORT SECRET=$ENYGMA_SESSION_SECRET"\n'
    (work / "probe.sh").write_text(body)

    out = subprocess.run(["bash", "probe.sh"], cwd=work, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert not proof.exists(), "a line in .env was executed"
    assert "PORT=4099" in out.stdout
    assert "SECRET=quoted-value" in out.stdout, "surrounding quotes should be stripped"
    assert "ignoring non-assignment line" in out.stderr, "stray lines must be reported"


def test_check_env_finds_the_mistakes_without_printing_secrets():
    import subprocess
    root = pathlib.Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "tools/check_env.py"],
                         cwd=root, capture_output=True, text=True)
    if "No .env at" in out.stdout:
        return  # nothing to check on a machine without one
    secret = ""
    for line in (root / ".env").read_text().splitlines():
        if line.startswith("ENYGMA_SESSION_SECRET="):
            secret = line.split("=", 1)[1].strip().strip("'\"")
    if secret:
        assert secret not in out.stdout, "check_env printed the session secret"


def test_the_mark_is_on_every_page_exactly_once_per_viewport():
    """Top right on desktop, in the header row on a handset. One element each,
    both fed from the same value so they cannot drift apart."""
    from src.config import config
    c = client()
    for path in PAGES:
        text = c.get(path).text
        assert text.count(config.MARK) >= 2, f"{path} is missing the mark"
        assert 'class="markbadge desk mono"' in text
        assert 'class="mobilebar"' in text


def test_healthz_reports_the_mark_alongside_the_build():
    body = client(signed_in=False).get("/healthz").json()
    assert body["mark"].startswith("Mk II."), body["mark"]
    assert body["version"].startswith(body["mark"].split(".")[-1] + "."), \
        "the build stamp should lead with the same commit number as the mark"


def test_a_recording_interrupted_mid_transcription_is_picked_up_again():
    """'transcribing' is set before the work starts. If the process dies in the
    gap -- a restart, the memory ceiling, a power cut -- the worker only ever
    claims 'queued', so that row would show a progress bar forever."""
    from src.db import cursor
    from src.pipeline import runner
    with cursor() as conn:
        conn.execute("INSERT INTO recordings (title, status, source, audio_path, sha256) "
                     "VALUES ('Interrupted', 'transcribing', 'upload', 'x.mp3', 'stucksha')")
        rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    assert runner.requeue_stuck() >= 1
    with cursor() as conn:
        row = conn.execute("SELECT status, failure FROM recordings WHERE id = ?",
                           (rid,)).fetchone()
        conn.execute("DELETE FROM recordings WHERE id = ?", (rid,))
    assert row["status"] == "queued"
    assert "Interrupted" in row["failure"]


def test_a_failing_backend_shows_a_reason_rather_than_hanging():
    """The first real Gemini call is the first time that code path runs. If it
    throws, the operator needs a sentence, not a spinner that never resolves."""
    from src.db import cursor
    from src.pipeline import runner

    class Exploding:
        def transcribe(self, path, mime):
            raise RuntimeError("429 rate limit from the model")
        def summarise(self, transcript):
            raise AssertionError("should never get here")

    with cursor() as conn:
        conn.execute("INSERT INTO recordings (title, status, source, audio_path, sha256) "
                     "VALUES ('Doomed', 'queued', 'upload', 'nope.mp3', 'doomsha')")
        rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    result = runner.process_one(backend=Exploding())
    assert result["status"] == "failed"
    assert "429 rate limit" in result["detail"]

    page = client().get(f"/meetings/{rid}")
    assert "429 rate limit" in page.text, "the reason must reach the screen"
    assert "Try again" in page.text, "and the retry must be offered"
    with cursor() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (rid,))


def test_copy_as_markdown_carries_the_timestamps_out_with_it():
    """A summary pasted somewhere else is exactly where an unsourced claim does
    damage, so every decision and question keeps the moment it came from."""
    import importlib
    from src.db import cursor
    seed = importlib.import_module("tools.seed_demo")
    seed.seed()
    with cursor() as conn:
        rid = conn.execute("SELECT id FROM recordings WHERE source='demo' "
                           "AND status='ready' ORDER BY id").fetchone()["id"]

    md = client().get(f"/meetings/{rid}/markdown")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    body = md.text
    assert body.startswith("# ")
    assert "## Decisions" in body and "## Actions" in body
    assert "`01:58`" in body, "decisions must carry their timestamp"
    assert "- [ ] " in body, "actions should be checkboxes"
    assert "not verified by the model" in body, "the caveat travels with the copy"
    # A speaker label means nothing outside the app; resolve it where we can.
    assert "Priya Raman" in body
    seed.clear()


def test_the_markdown_route_needs_a_session():
    assert client(signed_in=False).get("/meetings/1/markdown").status_code in (302, 401, 404)
