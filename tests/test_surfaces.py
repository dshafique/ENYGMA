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

PAGES = ["/", "/meetings", "/chat", "/actions", "/directory", "/library", "/settings"]


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
    for path in ["/", "/meetings", "/chat", "/actions", "/directory", "/library"]:
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


# ---------------------------------------------------------------- freshness
def _stale_client():
    """A session that is real but old: signed correctly, verified long ago."""
    import time
    from src.main import app
    c = TestClient(app, follow_redirects=False)
    old = time.time() - (cfg.config.REAUTH_MINUTES + 5) * 60
    c.cookies.set(session.cookie_name(), session.issue(verified_at=old))
    return c


def test_a_stale_session_can_still_read_every_page():
    """Going stale must not eject him. He keeps reading; only writes stop."""
    c = _stale_client()
    for path in PAGES:
        assert c.get(path).status_code == 200, f"{path} rejected a stale session"


def test_a_stale_session_can_still_read_what_the_page_already_shows():
    """Being able to see a summary but not copy it is a distinction with nothing
    behind it. Same for holding a word in a transcript he is already reading."""
    import importlib
    from src.db import cursor
    seed = importlib.import_module("tools.seed_demo")
    seed.seed()
    with cursor() as conn:
        rid = conn.execute("SELECT id FROM recordings WHERE source='demo' "
                           "AND status='ready' ORDER BY id").fetchone()["id"]
    c = _stale_client()
    assert c.get(f"/meetings/{rid}/markdown").status_code == 200
    assert c.get("/api/term?q=MQTT").status_code == 200
    assert c.get("/api/meetings").status_code == 200
    seed.clear()


def test_a_stale_session_is_refused_for_writes_and_says_which_kind_of_401():
    """This is the bug: upload came back 401 and the interface said nothing.
    The reason has to be machine-readable so the client can raise the sheet
    rather than bounce him to the lock screen."""
    c = _stale_client()
    r = c.post("/upload", files={"files": ("m.mp3", b"ID3" + b"\x11" * 4000, "audio/mpeg")})
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "stale"


def test_no_session_at_all_is_a_different_401_than_a_stale_one():
    r = client(signed_in=False).post("/upload",
                                     files={"files": ("m.mp3", b"ID3", "audio/mpeg")})
    assert r.status_code == 401
    assert r.json()["detail"]["reason"] == "locked"


def test_re_authenticating_makes_the_same_upload_succeed():
    """The whole point of the sheet: retry the thing he actually asked for."""
    c = _stale_client()
    payload = {"files": ("Board sync.mp3", b"ID3" + b"\x44" * 6000, "audio/mpeg")}
    assert c.post("/upload", files=payload).status_code == 401

    # What the sheet does: prove it is him, which reissues a fresh cookie.
    from src.auth import secrets_store
    secrets_store.set_pin("135790")
    ok = c.post("/auth/pin/verify", json={"pin": "135790"})
    assert ok.status_code == 200

    retried = c.post("/upload", files={"files": ("Board sync.mp3",
                                                 b"ID3" + b"\x44" * 6000, "audio/mpeg")})
    assert retried.status_code == 200
    assert retried.json()["results"][0]["ok"] is True


def test_the_sheet_is_present_on_every_page_that_can_write():
    c = client()
    for path in PAGES:
        text = c.get(path).text
        assert 'id="reauth"' in text, f"{path} has no re-auth sheet"
        assert 'id="reauth-pin"' in text, "the PIN fallback must be offered too"


# ------------------------------------------------------------ the gemini path
def test_the_gemini_backend_is_actually_installable():
    """The first real transcription failed on ImportError because google-genai
    was never in requirements.txt. 'gemini' must not silently mean 'broken'."""
    import pathlib as _p
    root = _p.Path(__file__).resolve().parent.parent
    reqs = (root / "requirements.txt").read_text()
    assert "google-genai" in reqs, "the Gemini backend has no dependency declared"


def test_a_missing_sdk_says_what_to_do_about_it():
    from src.pipeline.gemini import GeminiBackend
    import builtins
    real = builtins.__import__

    def blocked(name, *a, **kw):
        if name == "google" or name.startswith("google."):
            raise ImportError("no module named google")
        return real(name, *a, **kw)

    builtins.__import__ = blocked
    try:
        GeminiBackend()._get_client()
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        assert "pip install" in str(exc), "the error must name the fix"
    finally:
        builtins.__import__ = real


def test_inline_audio_is_base64_not_raw_bytes():
    """Raw bytes fail at the transport, so the error never mentions audio."""
    import pathlib as _p, base64, json as _json
    root = _p.Path(__file__).resolve().parent.parent
    audio = _p.Path(__file__).parent / "_tiny.mp3"
    audio.write_bytes(b"ID3" + b"\x77" * 512)
    captured = {}

    class Fake:
        class files:
            @staticmethod
            def upload(file):
                raise AssertionError("small file should go inline")
        class interactions:
            @staticmethod
            def create(model, input):
                captured["input"] = input
                class R: output_text = _json.dumps(
                    {"segments": [{"speaker": "SPEAKER 1", "start": "00:00",
                                   "end": "00:05", "text": "hello"}]})
                return R()

    from src.pipeline.gemini import GeminiBackend
    out = GeminiBackend(client=Fake()).transcribe(audio, "audio/mpeg")
    audio.unlink()
    assert out.segments[0].text == "hello"
    part = [p for p in captured["input"] if p.get("type") == "audio"][0]
    assert isinstance(part["data"], str), "inline audio must be base64 text"
    assert base64.b64decode(part["data"]) == b"ID3" + b"\x77" * 512


# ----------------------------------------------------------------- timestamps
def test_times_are_shown_in_the_operators_zone_not_utc():
    """A meeting recorded at ten past midnight read '5:11 AM'. SQLite stores UTC,
    which is right; the screen showed UTC, which is not."""
    from src import fmt
    from datetime import datetime, timezone
    stored = "2026-08-27 05:11:30"          # what SQLite wrote for a 00:11 local upload
    shown = fmt.clock(stored)
    expected = (datetime(2026, 8, 27, 5, 11, 30, tzinfo=timezone.utc)
                .astimezone(fmt._display_zone()).strftime("%-I:%M %p"))
    assert shown == expected
    assert fmt._parse(stored).tzinfo is not None, "parsed timestamps must be aware"


# ------------------------------------------------------------- pin and pairing
def test_a_four_digit_pin_is_allowed_but_a_repeated_one_is_not():
    from src.auth import secrets_store as ss
    ss.set_pin("0125")
    assert ss.verify_pin("0125") and not ss.verify_pin("0126")
    for bad in ("123", "1111", "abcd", "12345678901"):
        try:
            ss.set_pin(bad)
            raise AssertionError(f"{bad} should have been refused")
        except ValueError:
            pass


def test_the_lockout_grows_so_a_short_pin_is_still_a_real_lock():
    from src.auth.attempts import penalty_seconds
    assert penalty_seconds(5) == 30
    assert penalty_seconds(10) == 60
    assert penalty_seconds(20) == 240
    assert penalty_seconds(10_000) == 60 * 60, "and it is capped"
    # An exhaustive search of 10,000 combinations, five per round.
    rounds = 10_000 // 5
    assert sum(penalty_seconds(r * 5) for r in range(1, rounds)) > 60 * 60 * 24 * 30


def test_a_setup_code_enrols_one_device_once():
    from src.auth import secrets_store as ss
    made = ss.create_pairing_code("Fold 8")
    assert "-" in made["code"] and len(made["code"]) == 9
    assert ss.consume_pairing_code("AAAA-BBBB") is False
    assert ss.consume_pairing_code(made["code"], "Fold 8") is True
    assert ss.consume_pairing_code(made["code"]) is False, "single use"
    assert ss.pairing_outstanding() is False


def test_minting_a_setup_code_needs_a_fresh_session():
    """It is the one credential that creates other credentials."""
    assert _stale_client().post("/auth/pairing/new", json={}).status_code == 401
    assert client(signed_in=False).post("/auth/pairing/new", json={}).status_code == 401
    assert client().post("/auth/pairing/new", json={}).status_code == 200


def test_redeeming_a_code_signs_the_new_device_in():
    c = client()
    code = c.post("/auth/pairing/new", json={"note": "Fold"}).json()["code"]
    fresh = client(signed_in=False)
    assert fresh.get("/meetings").status_code == 302
    assert fresh.post("/auth/pairing/redeem",
                      json={"code": code, "deviceName": "Fold"}).status_code == 200
    assert fresh.get("/meetings").status_code == 200


def test_the_lock_screen_offers_the_setup_code_path_once_a_device_exists():
    """With nothing enrolled the first device just creates a passkey. The setup
    code only means anything once there is an account to join."""
    from src.db import cursor
    bare = client(signed_in=False).get("/lock").text
    assert "Create your passkey" in bare
    assert "Use a setup code" not in bare, "nothing to pair with yet"

    with cursor() as conn:
        conn.execute("INSERT INTO credentials (credential_id, public_key, device_name) "
                     "VALUES (?, ?, 'Desktop')", (b"cred-1", b"key-1"))
    try:
        page = client(signed_in=False).get("/lock").text
        assert "Unlock with passkey" in page
        assert "Set up this device" in page
        assert "Use PIN instead" in page, "a PIN was set earlier in this module"
    finally:
        with cursor() as conn:
            conn.execute("DELETE FROM credentials WHERE credential_id = ?", (b"cred-1",))


# ----------------------------------------------------------------------- PWA
def test_the_manifest_and_worker_are_served_from_the_root():
    """A service worker only controls the scope it is served from, and both are
    read before there is any session."""
    c = client(signed_in=False)
    man = c.get("/manifest.webmanifest")
    assert man.status_code == 200
    assert man.headers["content-type"].startswith("application/manifest+json")
    import json
    body = json.loads(man.content)
    assert body["display"] == "standalone"
    assert body["start_url"] == "/" and body["scope"] == "/"
    purposes = {i["purpose"] for i in body["icons"]}
    assert {"any", "maskable"} <= purposes, "Android needs a maskable icon"

    sw = c.get("/sw.js")
    assert sw.status_code == 200
    assert sw.headers["service-worker-allowed"] == "/"
    assert sw.headers["cache-control"] == "no-cache", "the worker itself must not be cached"


def test_every_declared_icon_exists_and_is_a_real_png():
    import json, pathlib as _p
    root = _p.Path(__file__).resolve().parent.parent
    body = json.loads((root / "src/static/manifest.webmanifest").read_text())
    for icon in body["icons"]:
        path = root / icon["src"].lstrip("/").replace("static/", "src/static/", 1)
        assert path.exists(), f"{icon['src']} is declared but missing"
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{icon['src']} is not a PNG"
        w, h = icon["sizes"].split("x")
        from struct import unpack
        head = path.read_bytes()[16:24]
        assert unpack(">II", head) == (int(w), int(h)), f"{icon['src']} is not {icon['sizes']}"


def test_the_worker_refuses_to_cache_anything_private():
    """Everything this app renders is private. A worker that caches pages leaves
    transcripts on the device outside the permissions that are the whole
    isolation story, and serves them back after a logout."""
    import pathlib as _p
    sw = (_p.Path(__file__).resolve().parent.parent / "src/static/sw.js").read_text()
    assert 'url.pathname.startsWith("/static/")' in sw
    assert 'url.searchParams.has("v")' in sw, "only immutable, versioned assets"
    assert "caches.open" in sw
    # No route that could hold private content may appear as a cache target.
    for private in ("/meetings", "/api/", "/auth/", "/chat", "/upload"):
        assert f'cache.put("{private}' not in sw and f"addAll" not in sw


def test_the_page_advertises_itself_as_installable():
    page = client().get("/").text
    assert 'rel="manifest"' in page
    assert 'name="apple-touch-icon"' not in page and 'rel="apple-touch-icon"' in page
    assert page.count('name="theme-color"') == 2, "one per colour scheme"
    assert 'navigator.serviceWorker' in page


def test_a_four_digit_entry_in_the_setup_code_box_is_named_as_a_pin():
    """0125 typed into the setup code field returned 'not valid or has expired',
    which is true and useless. It is a PIN, and the screen should say so."""
    from src.db import cursor
    with cursor() as conn:
        conn.execute("INSERT INTO credentials (credential_id, public_key, device_name) "
                     "VALUES (?, ?, 'Desktop')", (b"cred-2", b"key-2"))
    try:
        page = client(signed_in=False).get("/lock").text
    finally:
        with cursor() as conn:
            conn.execute("DELETE FROM credentials WHERE credential_id = ?", (b"cred-2",))
    assert "That is a PIN, not a setup code" in page
    assert "eight letters and numbers" in page
    assert "It is not your PIN." in page


# ------------------------------------------------------------------- library
def test_a_note_becomes_something_chat_can_find():
    from src import library
    library.add("Halcyon MQTT spec", (
        "The broker is configured with retained messages enabled on every sensor "
        "topic. On restart it replays the last retained value to any client that "
        "subscribes. This is intentional and is not a fault."))
    found = library.context_for("what happens to retained messages on restart?")
    assert found["sources"] and found["sources"][0]["title"] == "Halcyon MQTT spec"
    assert "replays the last retained value" in found["text"]


def test_an_unrelated_question_finds_nothing_rather_than_the_nearest_thing():
    """A coincidence presented as a source is exactly the confident wrongness
    this system refuses. Without a stopword list, a question about swallows
    matches a document about brokers because both contain 'what' and 'the'."""
    from src import library
    assert library.context_for("what is the airspeed velocity of a swallow?")["sources"] == []
    assert library.context_for("what should I have for lunch")["sources"] == []


def test_the_same_document_twice_is_one_document():
    from src import library
    body = "A runbook nobody reads until the night it matters."
    first = library.add("Runbook", body)
    again = library.add("Runbook copied", body)
    assert again["duplicate"] is True and again["id"] == first["id"]


def test_a_file_type_it_cannot_read_says_so_in_a_sentence():
    from src import library
    try:
        library.extract("slides.pptx", b"\x50\x4b\x03\x04junk")
        raise AssertionError("should have been refused")
    except library.Rejected as exc:
        assert "paste" in str(exc), "the refusal must offer the way round it"


def test_html_is_read_as_text_not_as_tags():
    from src import library
    text = library.extract("page.html", b"<html><style>p{color:red}</style>"
                                        b"<body><h1>Onboarding</h1>"
                                        b"<p>Standups are Tuesdays at 9.</p></body></html>")
    assert "Standups are Tuesdays at 9." in text
    assert "<" not in text and "color:red" not in text


def test_uploading_and_forgetting_a_document_over_http():
    c = client()
    res = c.post("/library/upload",
                 files={"files": ("gateway.md", b"# Gateway\n\nTwo gateways run "
                                                b"behind a shared subscription so "
                                                b"either can take the traffic.",
                                  "text/markdown")})
    assert res.status_code == 200
    added = res.json()["results"][0]
    assert added["ok"] and added["chunks"] >= 1

    page = c.get("/library").text
    assert "gateway" in page.lower()

    from src import library
    assert library.context_for("what happens if a gateway is lost")["sources"]

    assert c.post(f"/library/{added['id']}/forget").status_code == 200
    assert library.context_for("what happens if a gateway is lost")["sources"] == []


def test_the_library_needs_a_fresh_session_to_write_and_a_session_to_read():
    assert client(signed_in=False).get("/library").status_code == 302
    assert _stale_client().get("/library").status_code == 200, "reading stays open"
    assert _stale_client().post("/library/note",
                                json={"title": "x", "body": "y"}).status_code == 401


# ------------------------------------------------------------ action states
def test_an_action_can_be_rejected_without_pretending_it_was_done():
    """Declining something and not having got to it are different answers."""
    import importlib
    from src import actions as repo
    from src.db import cursor
    seed = importlib.import_module("tools.seed_demo")
    seed.seed()
    with cursor() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM action_items ORDER BY id")]

    repo.set_state(ids[0], "rejected", "Halcyon are doing it instead")
    repo.set_state(ids[1], "pending")
    repo.set_state(ids[2], "done")

    grouped = repo.listing()
    assert ids[0] in [a["id"] for a in grouped["rejected"]]
    assert ids[1] in [a["id"] for a in grouped["pending"]]
    assert ids[2] in [a["id"] for a in grouped["done"]]
    rejected = next(a for a in grouped["rejected"] if a["id"] == ids[0])
    assert rejected["state_note"] == "Halcyon are doing it instead"
    assert rejected["done_at"] is None, "rejected is not done"
    assert next(a for a in grouped["done"] if a["id"] == ids[2])["done_at"]

    # Only open items are what he still owes.
    assert repo.open_count() == repo.counts()["open"]
    assert ids[0] not in [a["id"] for a in repo.listing(include_done=False)["open"]]
    seed.clear()


def test_an_unknown_state_is_refused_rather_than_stored():
    from src import actions as repo
    from src.db import cursor
    with cursor() as conn:
        conn.execute("INSERT INTO recordings (title,status,source,sha256) "
                     "VALUES ('m','ready','upload','statesha')")
        rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute("INSERT INTO action_items (recording_id, text) VALUES (?, 'x')", (rid,))
        aid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    try:
        repo.set_state(aid, "maybe")
        raise AssertionError("should have been refused")
    except ValueError as exc:
        assert "maybe" in str(exc)
    assert client().post(f"/actions/{aid}/state", json={"state": "maybe"}).status_code == 400
    assert client().post(f"/actions/{aid}/state", json={"state": "pending"}).status_code == 200
    with cursor() as conn:
        conn.execute("DELETE FROM recordings WHERE id = ?", (rid,))


def test_every_page_that_shows_an_action_offers_the_same_four_states():
    c = client()
    for path in ("/", "/actions"):
        text = c.get(path).text
        assert 'class="statepick"' in text or "No recordings" in text or "Nothing" in text
    from src import actions as repo
    assert repo.STATES == ("open", "pending", "done", "rejected")


def test_a_panel_that_starts_hidden_actually_stays_hidden():
    """A scar. `.wn-words-box { display: flex }` is a class rule in the author
    stylesheet, and the `hidden` attribute is a `display: none` in the browser's
    own, so the flex won and the box opened itself the moment it was styled. It
    rendered correctly in every test that only asked whether the markup was
    there, which is how it got as far as a screenshot.

    Generalised: any class that sets a display and is worn by an element written
    with `hidden` must also say what hidden looks like.
    """
    import re
    root = pathlib.Path(__file__).resolve().parent.parent
    css = (root / "src/static/css/app.css").read_text()

    displayed = {m.group(1) for m in
                 re.finditer(r"\.([a-z0-9-]+)\s*(?:,[^{]*)?\{[^}]*display:\s*(?!none)",
                             css)}
    guarded = set(re.findall(r"\.([a-z0-9-]+)\[hidden\]", css))

    starts_hidden = set()
    for page in (root / "src/templates").glob("*.html"):
        # `aria-hidden="true"` is a different attribute and always present.
        for tag in re.findall(r"<[a-z]+[^>]*(?<![-\w])hidden(?=[\s/>])[^>]*>",
                              page.read_text()):
            found = re.search(r'class="([^"]*)"', tag)
            if found:
                starts_hidden.update(found.group(1).split())

    unguarded = sorted((starts_hidden & displayed) - guarded)
    assert not unguarded, (
        "these classes set a display and are worn by an element that starts "
        f"hidden, so hidden does nothing: {unguarded}")
