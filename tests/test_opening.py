"""Opening the app: the animation, and what changed since he last looked.

Both fire on launch, so both are tested for the same thing above all else: they
must not get in the way of somebody who opened the app to write one line down
before they forget it.
"""
import os, sys, json, pathlib, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from src import db, config as cfg                # noqa: E402
from src.ingest import upload                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"; upload.BASE_DIR = tmp
    db.migrate()


# ------------------------------------------------------------- what changed

def test_a_device_that_has_been_here_is_shown_what_it_missed():
    from src import changelog
    got = changelog.since("Mk II.25")
    assert [r["mark"] for r in got] == ["Mk II.29"]
    assert changelog.since("Mk II.18")[0]["mark"] == "Mk II.29"
    assert len(changelog.since("Mk II.18")) == 2


def test_a_device_that_is_current_is_shown_nothing():
    from src import changelog
    assert changelog.since(changelog.latest()) == []


def test_a_new_device_is_not_handed_the_whole_history():
    """A wall of releases is not a welcome."""
    from src import changelog
    assert changelog.since(None) == []
    assert changelog.since("") == []
    assert changelog.since("Mk II.3") == [], "an unknown build dumped everything"


def test_entries_are_about_what_he_can_now_do():
    """The commit messages here are long-form prose for whoever maintains this.
    A changelog is a different document for a different person, and the give-away
    when they get confused is engineering vocabulary."""
    from src import changelog
    for release in changelog.RELEASES:
        assert release["items"], release["mark"]
        assert len(release["items"]) <= 5, f"{release['mark']} is too long to finish"
        joined = " ".join(release["items"]).lower()
        for word in ("refactor", "migration", "endpoint", "backend", "regression",
                     "commit", "test suite"):
            assert word not in joined, f"{release['mark']} says {word!r}"


def test_the_newest_release_is_first():
    from src import changelog
    assert changelog.RELEASES[0]["mark"] == changelog.latest()


# --------------------------------------------------------------- the opening

def _css() -> str:
    return (ROOT / "src/static/css/app.css").read_text()


def test_the_opening_plays_once_per_launch_not_once_per_tap():
    """Every page here is a real navigation. Without this it would replay on
    every single one, which turns a nice thing into a tax on using the app."""
    html = (ROOT / "src/templates/base.html").read_text()
    assert 'sessionStorage.getItem("enygma-opened")' in html
    assert "splash-done" in html
    assert "html.splash-done .splash { display: none; }" in _css()


def test_it_can_always_be_tapped_away():
    """It is under two seconds, but two seconds is a long time to somebody who
    opened the app to write one line down before they forget it."""
    js = (ROOT / "src/static/js/app.js").read_text()
    block = js[js.index("the opening */"):js.index("what changed */")]
    assert '"pointerdown"' in block
    assert "splash.remove()" in block
    # And a safety net that outlasts the animation rather than cutting it off.
    assert "setTimeout(skip, 1750)" in block


def test_the_safety_net_outlasts_the_animation():
    """A timer that fires before the last frame does not rescue him from
    anything, it just breaks the thing."""
    import re
    css = _css()
    fade = re.search(r"animation: splash-out \d+ms var\(--ease\) (\d+)ms both", css)
    assert fade, "the fade is not where this test thinks it is"
    ends_at = int(fade.group(1)) + 380
    js = (ROOT / "src/static/js/app.js").read_text()
    net = int(re.search(r"setTimeout\(skip, (\d+)\)", js).group(1))
    assert net > ends_at, f"the net fires at {net}ms, the animation ends at {ends_at}ms"


def test_nobody_who_asked_for_less_motion_has_to_sit_through_it():
    css = _css()
    block = css[css.index("@media (prefers-reduced-motion: reduce) {",
                          css.index("Opening")):]
    block = block[:block.index("}\n\n")]
    assert ".splash-mark i, .splash-rule, .splash-word { animation: none; }" in block
    assert ".splash-mark i.void { opacity: 0; }" in block


def test_the_mark_in_the_opening_is_the_mark():
    """Four voids, in the four places _mark.html puts them, or it is a different
    mark with the same name."""
    base = (ROOT / "src/templates/base.html").read_text()
    splash = base[base.index('class="splash-mark"'):base.index("splash-rule")]
    assert "n in [0, 6, 9, 15]" in splash

    macro = (ROOT / "src/templates/_mark.html").read_text()
    cells = macro[macro.index('aria-label="ENYGMA"'):macro.index("</div>")]
    voids = {n for n, piece in enumerate(cells.split("<i")[1:]) if "void" in piece}
    assert voids == {0, 6, 9, 15}, f"the app's mark has voids at {voids}"


# --------------------------------------------- the number is not written by hand

def test_a_new_entry_is_numbered_by_the_stamper_not_by_a_person():
    """Writing it by hand looked fine and was wrong. The number is the commit
    count, so committing the changelog entry changed the number the entry
    claimed, and the changelog quietly described a build that never existed."""
    import shutil, subprocess
    work = pathlib.Path(tempfile.mkdtemp())
    (work / "src").mkdir()
    (work / "tools").mkdir()
    shutil.copy(ROOT / "src/changelog.py", work / "src/changelog.py")
    shutil.copy(ROOT / "tools/stamp_release.py", work / "tools/stamp_release.py")

    # A fresh entry, the way one is written.
    text = (work / "src/changelog.py").read_text()
    text = text.replace("RELEASES = [\n    {\n",
                        'RELEASES = [\n    {\n        "mark": UNRELEASED,\n'
                        '        "date": "2026-09-09",\n'
                        '        "headline": "Something new",\n'
                        '        "items": ["It does a thing now."],\n    },\n    {\n', 1)
    (work / "src/changelog.py").write_text(text)

    out = subprocess.run([sys.executable, str(work / "tools/stamp_release.py"),
                          "--count", "77"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    after = (work / "src/changelog.py").read_text()
    assert '"mark": "Mk II.77",' in after, out.stdout
    assert (work / "MARK").read_text().strip() == "Mk II.77"


def test_a_release_that_already_has_a_number_is_never_renumbered():
    """A device that has been shown a release must not be shown it again under a
    new name."""
    import shutil, subprocess
    work = pathlib.Path(tempfile.mkdtemp())
    (work / "src").mkdir(); (work / "tools").mkdir()
    shutil.copy(ROOT / "src/changelog.py", work / "src/changelog.py")
    shutil.copy(ROOT / "tools/stamp_release.py", work / "tools/stamp_release.py")

    subprocess.run([sys.executable, str(work / "tools/stamp_release.py"),
                    "--count", "40"], capture_output=True, text=True)
    once = (work / "src/changelog.py").read_text()
    subprocess.run([sys.executable, str(work / "tools/stamp_release.py"),
                    "--count", "41"], capture_output=True, text=True)
    twice = (work / "src/changelog.py").read_text()
    assert once == twice, "a second stamp renumbered a release that had shipped"


def test_nothing_unreleased_survives_into_a_build():
    """A packaged build always has a stamped changelog, because packaging stamps
    it. An UNRELEASED mark reaching a device would show up as a release with no
    name."""
    from src import changelog
    if (ROOT / "MARK").exists():
        assert changelog.RELEASES[0]["mark"] != changelog.UNRELEASED, \
            "run tools/stamp_release.py"


def test_the_newest_entry_describes_the_build_that_is_stamped():
    """The whole point of moving the number out of a person's hands."""
    from src import changelog
    stamped = (ROOT / "MARK")
    if not stamped.exists():
        return
    assert changelog.latest() == stamped.read_text().strip()
