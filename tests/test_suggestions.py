"""Work nobody picked up, and the rules that keep it from being slop.

The risk this feature carries is specific and was named plainly: he glances at
something ENYGMA guessed, reads it as an assignment, and tells his manager he is
doing work nobody asked for. Every test here is a guard on that.
"""
import os, sys, pathlib, tempfile, json

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from src import db, config as cfg                        # noqa: E402


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    cfg.config.INSECURE_COOKIES = True
    db.migrate()


class Backend:
    model = "fake"

    def __init__(self, payload):
        self.payload = payload
        self.asked = []

    def _ask(self, parts, schema=None):
        self.asked.append(parts[0]["text"])
        return json.dumps(self.payload)


def _a_meeting(title="LEAF stand up") -> int:
    with db.cursor() as conn:
        conn.execute("INSERT INTO recordings (title, status, recorded_at) "
                     "VALUES (?, 'ready', date('now'))", (title,))
        rid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        conn.execute("INSERT INTO summaries (recording_id, abstract, topics, "
                     "decisions, questions) VALUES (?, 'They met.', '[]', '[]', '[]')",
                     (rid,))
    return rid


# --------------------------------------------------------- what gets stored

def test_a_suggestion_that_cannot_cite_a_meeting_is_thrown_away():
    """An uncited suggestion is a rumour. He has to be able to go and listen to
    the moment, or he cannot tell a real gap from an invented one."""
    from src import suggestions
    rid = _a_meeting()
    out = suggestions.look(backend=Backend({"gaps": [
        {"gap": "Real thing", "why": "Seen here", "could": "Do it", "meeting_id": rid},
        {"gap": "Invented thing", "why": "Nowhere", "could": "Do it",
         "meeting_id": 99999},
    ]}))
    assert out["found"] == 1
    assert [s["gap"] for s in suggestions.offered()] == ["Real thing"]


def test_a_suggestion_missing_its_evidence_is_thrown_away():
    """Without the why, the folded note is an instruction with no argument
    behind it, which is exactly the shape of career-advice slop."""
    from src import suggestions
    rid = _a_meeting()
    before = len(suggestions.offered())
    suggestions.look(backend=Backend({"gaps": [
        {"gap": "No reason given", "why": "", "could": "Do it", "meeting_id": rid}]}))
    assert len(suggestions.offered()) == before


def test_the_model_is_told_what_is_already_owned():
    """Otherwise it offers him work Joseph is in the middle of, which is worse
    than offering him nothing."""
    from src import suggestions
    rid = _a_meeting()
    with db.cursor() as conn:
        conn.execute("INSERT INTO speakers (recording_id, label, turns, person_name) "
                     "VALUES (?, 'SPEAKER 2', 1, 'Joseph Kudia')", (rid,))
        conn.execute("INSERT INTO action_items (recording_id, text, owner) "
                     "VALUES (?, 'Build the camera module', 'SPEAKER 2')", (rid,))
    backend = Backend({"gaps": []})
    suggestions.look(backend=backend)
    asked = backend.asked[0]
    assert "ALREADY OWNED" in asked
    assert "Joseph Kudia" in asked and "Build the camera module" in asked


def test_the_same_gap_is_not_offered_twice():
    """A surface that keeps proposing something he has already turned down stops
    being read."""
    from src import suggestions
    rid = _a_meeting()
    suggestions.look(backend=Backend({"gaps": [
        {"gap": "Image expiry", "why": "Nobody took it", "could": "Look at it",
         "meeting_id": rid}]}))
    backend = Backend({"gaps": []})
    suggestions.look(backend=backend)
    assert "ALREADY OFFERED" in backend.asked[0]
    assert "Image expiry" in backend.asked[0]


# ------------------------------------------------- it is not an obligation

def test_a_suggestion_is_in_no_count_and_on_no_other_surface():
    """The structural guarantee. Suggestions live in their own table, so no
    careless join can put a guess into his list of obligations."""
    from src import suggestions, actions
    rid = _a_meeting()
    suggestions.look(backend=Backend({"gaps": [
        {"gap": "Something spare", "why": "Nobody has it", "could": "Take it",
         "meeting_id": rid}]}))
    listing = actions.listing()
    assert not any("Something spare" in a["text"] for a in listing["open"])
    assert all("Something spare" not in t["label"] for t in listing["targets"])


def test_taking_one_makes_an_ordinary_action_item_with_his_name_on_it():
    """The moment he accepts, it stops being a guess. It should look like every
    other commitment, because by then it is one."""
    from src import suggestions, actions
    rid = _a_meeting()
    cfg.config.OWNER_NAME = "Yahya Shafique"
    try:
        suggestions.look(backend=Backend({"gaps": [
            {"gap": "The schema", "why": "Between two people", "could":
             "Write the schema down", "meeting_id": rid}]}))
        offer = suggestions.offered()[0]
        out = suggestions.take(offer["id"])
        assert out["action_id"]
        mine = actions.listing(who=["Yahya Shafique"])
        assert any(a["text"] == "Write the schema down" for a in mine["open"])
    finally:
        cfg.config.OWNER_NAME = ""


def test_taking_the_same_one_twice_makes_one_commitment_not_two():
    from src import suggestions
    rid = _a_meeting()
    suggestions.look(backend=Backend({"gaps": [
        {"gap": "Once only", "why": "Nobody has it", "could": "Do the thing",
         "meeting_id": rid}]}))
    offer = suggestions.offered()[0]
    assert suggestions.take(offer["id"]) is not None
    assert suggestions.take(offer["id"]) is None, "a second press made a second item"


def test_passing_one_puts_it_away_without_deleting_it():
    from src import suggestions
    rid = _a_meeting()
    suggestions.look(backend=Backend({"gaps": [
        {"gap": "Not for him", "why": "Nobody has it", "could": "Do the thing",
         "meeting_id": rid}]}))
    offer = next(s for s in suggestions.offered() if s["gap"] == "Not for him")
    assert suggestions.pass_on(offer["id"]) is True
    assert not any(s["gap"] == "Not for him" for s in suggestions.offered())
    with db.cursor() as conn:
        kept = conn.execute("SELECT state FROM suggestions WHERE id = ?",
                            (offer["id"],)).fetchone()
    assert kept["state"] == "passed", "it was deleted, so it can be offered again"


# --------------------------------------------------------- what it says

def test_nothing_is_phrased_as_an_instruction():
    """Read over a shoulder or on a lock screen, a suggestion must still not
    tell him to do anything."""
    page = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/suggestions.html").read_text()
    assert "You could" in page, "the move is phrased as an order"
    from src import suggestions
    assert "never\n  as an instruction" in suggestions.FIND_PROMPT or \
           "never as an instruction" in " ".join(suggestions.FIND_PROMPT.split())


def test_the_warning_is_not_dismissible():
    """It is the first thing on the surface every single time, because the risk
    is him telling someone he is doing work nobody asked for."""
    page = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/suggestions.html").read_text()
    start = page.index("nobodyhead")
    head = page[start:page.index("</div>", start)]
    assert "not assigned to you" in head
    assert "<details" not in head, "the warning can be folded away"
    assert "hidden" not in head and "dismiss" not in head


def test_the_prompt_refuses_to_give_career_advice():
    """The failure mode this feature has to avoid is "take ownership of
    cross-functional alignment"."""
    from src import suggestions
    flat = " ".join(suggestions.FIND_PROMPT.split())
    assert "No advice about how he should behave, present himself, or be perceived" in flat
    assert "Only work that is genuinely unheld" in flat


def test_they_are_shut_by_default():
    """The closed state carries a subject and no argument, so reading one is a
    decision rather than an accident."""
    page = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/suggestions.html").read_text()
    assert "<details class=\"offer\"" in page
    assert "<details class=\"offer\" open" not in page
