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
    """Deliberately no hard-coded release number. The number is assigned by the
    stamper now, and a test that pins it would have to be edited on every
    release, which is the coupling that was just removed."""
    from src import changelog
    released = changelog.released()
    if len(released) < 2:
        return
    # Structural, not counted: from the second-newest, he sees exactly the
    # newest. Counting releases means editing this on every release, which is
    # the coupling that keeps growing back.
    got = changelog.since(released[1]["mark"])
    assert [r["mark"] for r in got] == [changelog.latest()]
    # And from further back, everything after that point, in order.
    oldest = released[-1]["mark"]
    assert [r["mark"] for r in changelog.since(oldest)] == \
        [r["mark"] for r in released[:-1]]


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
    """Between writing an entry and stamping it, the top of the list is
    UNRELEASED and has no number to compare. That is a working state, not a
    broken one, so it is skipped rather than failed."""
    from src import changelog
    if changelog.RELEASES[0]["mark"] == changelog.UNRELEASED:
        return
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


def test_an_unreleased_entry_is_never_offered_to_a_device():
    """Between writing an entry and stamping it the top of the list has no
    number, which is a working state. What must never happen is that entry
    reaching a phone, where it would appear as a release with no name."""
    from src import changelog
    assert changelog.UNRELEASED not in [r["mark"] for r in changelog.released()]
    assert changelog.latest() != changelog.UNRELEASED
    for mark in (None, "Mk II.25", changelog.latest()):
        assert changelog.UNRELEASED not in [r["mark"] for r in changelog.since(mark)]


def test_the_changelog_never_claims_a_build_that_does_not_exist_yet():
    """Behind the build is normal; ahead of it is a lie.

    The build number increments on every commit. The changelog only gains an
    entry when there is something to tell him, so a release that fixed a test
    has a number and no entry, and the newest entry is legitimately older than
    the build. What must never happen is the reverse: an entry numbered higher
    than anything that has been built describes a release nobody can run, which
    is the exact failure that moving the number out of a person's hands was
    meant to prevent.
    """
    from src import changelog
    stamped = ROOT / "MARK"
    if not stamped.exists() or not changelog.latest():
        return

    def number(mark: str) -> int:
        return int(mark.rsplit(".", 1)[1])

    assert number(changelog.latest()) <= number(stamped.read_text().strip()), (
        f"changelog says {changelog.latest()}, the build is "
        f"{stamped.read_text().strip()}")


# ------------------------------------------- the installer's own report

def test_the_env_checker_knows_every_setting_the_app_reads():
    """It was a hand-kept list and went stale the first time a setting was
    added: a real, working ENYGMA_ANTHROPIC_API_KEY was reported on the Spark as
    "not a setting ENYGMA reads", in the middle of the output an operator is
    told to trust. A checker confidently wrong about a key is worse than none,
    because the next true warning it prints gets ignored too.
    """
    import re, importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_env", ROOT / "tools/check_env.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)

    reads = set(re.findall(r'"(ENYGMA_[A-Z0-9_]+)"',
                           (ROOT / "src/config.py").read_text()))
    assert reads, "no settings found in config.py; this test is looking in the wrong place"
    missing = reads - checker.KNOWN
    assert not missing, f"the checker would call these unknown: {sorted(missing)}"

    # And specifically the ones that were missing when this was found.
    for name in ("ENYGMA_ANTHROPIC_API_KEY", "ENYGMA_OLLAMA_MODEL",
                 "ENYGMA_CHAT_DEFAULT", "ENYGMA_SPEND_STEP_DOLLARS"):
        assert name in checker.KNOWN, name


def test_the_list_is_derived_rather_than_written_down():
    """A list a person maintains is a list that goes stale. This one is read out
    of config.py, so adding a setting adds it here."""
    source = (ROOT / "tools/check_env.py").read_text()
    assert "def known_settings()" in source
    assert "KNOWN = known_settings()" in source
    # No hand-written set left behind to drift alongside it.
    assert '"ENYGMA_PORT", "ENYGMA_HOST"' not in source


def test_the_app_does_not_override_the_phones_rotation_lock():
    """"orientation": "any" is an explicit claim that the app handles every
    orientation, which is what makes Android ignore his rotation lock. Saying
    nothing defers to the phone, which is what he asked for."""
    import json
    manifest = json.loads((ROOT / "src/static/manifest.webmanifest").read_text())
    assert "orientation" not in manifest, (
        f"the manifest claims orientation {manifest.get('orientation')!r}")


def test_everything_pinned_to_the_bottom_clears_the_measured_keyboard():
    """interactive-widget=resizes-content is a Chrome feature. Samsung Internet
    is the default browser on the phone this runs on and does not honour it, so
    the layout viewport never shrinks and anything stuck to its bottom is behind
    the keyboard. visualViewport always knows."""
    css = (ROOT / "src/static/css/app.css").read_text()
    js = (ROOT / "src/static/js/app.js").read_text()
    assert "visualViewport" in js
    assert '--kb' in js, "nothing publishes the measurement"
    block = js[js.index("the keyboard */"):js.index("the opening */")]
    assert "window.innerHeight - vv.height" in block
    # The two things that sit on the bottom edge.
    assert "bottom: var(--kb, 0px)" in css
    assert "inset: auto 0 var(--kb, 0px) 0" in css


def test_a_var_with_a_fallback_is_not_a_token_violation():
    """The linter exists because an undefined property silently drops the whole
    declaration. A fallback makes that impossible, and runtime values like the
    keyboard inset have no business in a token file."""
    import subprocess
    out = subprocess.run([sys.executable, str(ROOT / "tools/check_tokens.py")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    source = (ROOT / "tools/check_tokens.py").read_text()
    assert r"var\(\s*(--[a-z0-9-]+)\s*\)" in source, "it still flags fallbacks"
