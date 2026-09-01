"""The Friday note.

The rules that matter here are the ones a prompt cannot be trusted with: it must
not sound like a machine, it must not invent a week that did not happen, and it
must not promise his manager something he never agreed to. So those are tested
against a backend that deliberately misbehaves, not against a good day.
"""
import os, sys, pathlib, tempfile, json
from datetime import date, datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from src import db, config as cfg                # noqa: E402
from src.ingest import upload                    # noqa: E402


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"; upload.BASE_DIR = tmp
    db.migrate()


class Backend:
    """A model that writes like a model, until it is told twice."""
    model = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked = []

    def _ask(self, parts, schema=None):
        self.asked.append(parts[0]["text"])
        return self.replies.pop(0) if self.replies else json.dumps(
            {"done": ["Fixed the thing."], "next": ["Finish the thing."]})


# ------------------------------------------------------------------- voice

def test_em_dashes_and_semicolons_never_survive():
    """His whole brief was that it must not look like it came from an AI, and an
    em dash in a Friday email to a manager is a fingerprint."""
    from src import weeknote
    out = weeknote.clean(["Cut the query down — it now takes four seconds",
                          "Fixed the timer; it was resetting on the wrong event"])
    assert "—" not in " ".join(out) and ";" not in " ".join(out)
    assert out == ["Cut the query down, it now takes four seconds",
                   "Fixed the timer, it was resetting on the wrong event"]


def test_smart_quotes_are_flattened():
    from src import weeknote
    assert weeknote.plain("It’s the “export” job") == "It's the \"export\" job"


def test_the_model_is_told_which_words_it_used_and_asked_again():
    """A bare retry repeats the mistake with more confidence. Naming the words is
    what makes the second attempt different."""
    from src import weeknote
    backend = Backend(
        json.dumps({"done": ["Leveraged the pipeline to streamline delivery"],
                    "next": ["Circle back on the robust solution"]}),
        json.dumps({"done": ["Made the export faster"], "next": ["Finish the export"]}),
    )
    found = {"meetings": [], "closed": [{"id": 1, "text": "x", "meeting": "m"}],
             "rejected": [], "owed": [], "documents": [], "notes": []}
    cfg.config.PIPELINE = "gemini"
    try:
        out = weeknote.compose(found, backend=backend)
    finally:
        cfg.config.PIPELINE = "stub"
    assert len(backend.asked) == 2, "it did not ask again"
    for word in ("leveraged", "streamline", "circle back", "robust"):
        assert word in backend.asked[1].lower(), f"{word} was not named in the retry"
    assert out["done"] == ["Made the export faster"]


def test_a_model_that_will_not_behave_gets_its_bullets_dropped():
    """A shorter honest note beats a long one that reads like a press release."""
    from src import weeknote
    bad = json.dumps({"done": ["Leveraged synergies across the stack",
                               "Fixed the login bug"],
                      "next": ["Circle back with stakeholders"]})
    backend = Backend(bad, bad)
    found = {"meetings": [], "closed": [{"id": 1, "text": "x", "meeting": "m"}],
             "rejected": [], "owed": [], "documents": [], "notes": []}
    cfg.config.PIPELINE = "gemini"
    try:
        out = weeknote.compose(found, backend=backend)
    finally:
        cfg.config.PIPELINE = "stub"
    assert out["done"] == ["Fixed the login bug"]
    assert out["next"] == []


def test_no_more_than_five_bullets():
    from src import weeknote
    assert len(weeknote.clean([f"Line {n}" for n in range(20)])) == 5


# -------------------------------------------------------------- the window

def test_the_week_runs_monday_to_friday():
    from src import weeknote
    start, end = weeknote.week_bounds(date(2026, 9, 2))   # a Wednesday
    assert (start, end) == (date(2026, 8, 31), date(2026, 9, 4))


def test_the_weekend_still_belongs_to_the_week_that_just_ended():
    """A note opened on Sunday is about the week he just finished, not the one
    that has not started."""
    from src import weeknote
    for day in (date(2026, 9, 5), date(2026, 9, 6)):      # Sat, Sun
        start, end = weeknote.week_bounds(day)
        assert (start, end) == (date(2026, 8, 31), date(2026, 9, 4))


# ------------------------------------------------------------- honest gaps

def test_an_empty_week_is_not_written_up():
    from src import weeknote
    found = weeknote.material(date(2020, 1, 6), date(2020, 1, 10))
    assert weeknote.is_empty(found)
    assert weeknote.compose(found)["done"] == []


def test_a_quiet_week_is_never_due():
    """An empty row on Home would read as a broken feature. Nothing is better."""
    from src import weeknote
    assert weeknote.write_if_due(datetime(2020, 1, 11, 18, 0)) is None


# ------------------------------------------------------------ his own words

def _seed_a_week(monday: date) -> None:
    from src import actions
    with db.cursor() as conn:
        conn.execute("INSERT INTO recordings (title, status, recorded_at) "
                     "VALUES ('LEAF weekly', 'ready', ?)", (monday.isoformat(),))
        rid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        conn.execute("INSERT INTO summaries (recording_id, abstract, decisions, questions) "
                     "VALUES (?, 'The team met.', '[]', '[]')", (rid,))
        conn.execute("INSERT INTO action_items (recording_id, text) VALUES (?, 'Fix the export')",
                     (rid,))
        aid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    actions.set_state(aid, "done")
    with db.cursor() as conn:
        conn.execute("UPDATE action_items SET state_at = ? WHERE id = ?",
                     (monday.isoformat() + " 12:00:00", aid))


def test_his_edit_survives_the_automatic_friday_write():
    """The worst possible bug in this feature: he fixes a line, Friday comes
    round, and the machine quietly replaces what he wrote."""
    from src import weeknote
    monday = date(2026, 8, 31)
    _seed_a_week(monday)
    weeknote.write(monday)
    weeknote.save_edit(monday.isoformat(), ["My own words"], ["My own plan"])

    weeknote.write(monday, keep_edit=True)          # what Friday does
    assert weeknote.stored(monday)["done"] == ["My own words"]


def test_writing_it_again_on_purpose_does_replace_his_edit():
    """He pressed the button that says it. Keeping the old edit would be worse."""
    from src import weeknote
    monday = date(2026, 8, 31)
    weeknote.save_edit(monday.isoformat(), ["My own words"], [])
    again = weeknote.write(monday, keep_edit=False)
    assert again["done"] != ["My own words"]
    assert again["edited"] is False


def test_the_copied_text_is_plain_enough_for_an_email():
    from src import weeknote
    text = weeknote.as_email({"done": ["Fixed the export"], "next": ["Finish it"]})
    assert text == ("What I got done this week\n- Fixed the export\n\n"
                    "What I am working on next week\n- Finish it")
    assert "*" not in text and "#" not in text


def test_rejected_actions_are_shown_to_the_model_as_not_done():
    """Turning something down is a decision, not an achievement. Listing it under
    'what I got done' would be a lie told to his manager in his name."""
    from src import weeknote
    found = {"meetings": [], "closed": [], "rejected": [{"id": 9, "text": "Rebuild the admin"}],
             "owed": [], "documents": [], "notes": []}
    brief = weeknote._brief(found)
    assert "Do not list them as done" in brief and "Rebuild the admin" in brief


def test_next_week_only_covers_what_he_owes():
    from src import weeknote
    found = {"meetings": [], "closed": [], "rejected": [], "documents": [], "notes": [],
             "owed": [{"id": 3, "text": "Finish the export", "state": "open",
                       "meeting": "LEAF weekly"}]}
    brief = weeknote._brief(found)
    assert "Only include one if HE is the person doing it" in brief


def test_the_provenance_line_reads_like_a_sentence():
    from src import weeknote
    assert weeknote.drawn_from({
        "meetings": [1, 2, 3, 4], "closed": [1] * 6, "notes": [1, 2],
        "documents": [], "rejected": [], "owed": []}
    ) == "4 meetings, 6 actions you closed and 2 sets of notes"
    assert weeknote.drawn_from({"meetings": [1], "closed": [], "notes": [],
                                "documents": [], "rejected": [], "owed": []}) == "1 meeting"
