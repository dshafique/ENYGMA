"""Not sounding like a machine.

He puts his name on what comes out of this app, so nothing leaving it should
announce that a model wrote it. Three separate habits give it away and they need
three separate answers: the vocabulary, the typography, and the shape.

The rule that matters most here is the one about what must NOT be caught. His
brother works on hardware. I2C, MOSFET, EZO and pull-up resistor are the
substance of the writing, not decoration on it, and a filter that flattens those
has made the document worse while congratulating itself.
"""
import os, sys, pathlib, tempfile, json

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


# --------------------------------------------------- what must NOT be caught

def test_his_actual_field_is_never_treated_as_jargon():
    """The failure mode that would make this feature a net loss."""
    from src import voice
    real = [
        "Opted for hardware pull-up resistors on I2C due to noise from MOSFET switching.",
        "Calibrated the EZO CO2 sensor and logged the drift above 80 percent RH.",
        "Routed the gates to Jacob's control board and reflashed the firmware.",
        "Diarization collapses past the thirty minute mark, so the audio is windowed.",
        "The bus address moved from 0x27 to 0x61 after the swap.",
        "Cut the query down with an index on recorded_at and it runs in four seconds.",
    ]
    assert voice.offences(real) == [], voice.offences(real)
    assert voice.tells(real) == [], voice.tells(real)
    # And the words come through the mechanical pass untouched.
    for line in real:
        assert voice.tidy(line) == line, line


def test_a_semicolon_inside_a_command_is_not_a_semicolon_in_prose():
    """Rewriting punctuation inside code corrupts the thing he asked for."""
    from src import voice
    answer = (
        "Run this once, then check the log.\n\n"
        "```bash\n"
        "i2cdetect -y 1; echo \"done\" --verbose\n"
        "```\n\n"
        "If it hangs; power cycle the rail.\n"
    )
    out = voice.tidy_markdown(answer)
    assert 'i2cdetect -y 1; echo "done" --verbose' in out, "the command was mangled"
    assert "If it hangs, power cycle" in out, "the prose was not tidied"
    # And the command is not read when deciding whether to ask again.
    assert "--verbose" not in " ".join(voice.prose_lines(answer))


# ------------------------------------------------------- what must be caught

def test_the_consultancy_words():
    from src import voice
    found = voice.offences(["We leveraged the pipeline to streamline a robust, "
                            "seamless deep dive into key learnings."])
    for word in ("leveraged", "streamline", "robust", "seamless",
                 "deep dive", "key learnings"):
        assert word in found, f"{word} not caught: {found}"


def test_the_chat_window_words():
    from src import voice
    found = voice.offences(["Certainly! Let me delve into that. "
                            "I hope this helps, feel free to reach out."])
    assert "delve" in found and "i hope this helps" in found


def test_the_shapes_that_give_it_away_even_with_clean_words():
    """A document can contain no banned word and still be unmistakable."""
    from src import voice
    assert "a bullet that opens with a bolded label and a colon" in voice.tells(
        ["**Technical Decisions:** we moved to pull-up resistors"])
    assert "handing the document over inside the document" in voice.tells(
        ["Here is your LOGBOOK.md template."])
    assert "an essay frame around a note" in voice.tells(["Introduction"])
    assert "an emoji" in voice.tells(["Shipped it 🚀"])
    assert "an essay connective" in voice.tells(["Furthermore, the rail is live."])


def test_the_bolded_lead_in_becomes_a_sentence_not_a_deletion():
    """The information survives. Only the tic goes."""
    from src import voice
    assert voice.tidy("**Blockers:** waiting on Joseph to flash the firmware") \
        == "Blockers: waiting on Joseph to flash the firmware"


def test_the_typography_a_phone_would_never_produce():
    from src import voice
    assert voice.tidy("It runs — just about — at four seconds") \
        == "It runs, just about, at four seconds"
    assert voice.tidy("Fixed the timer; it was wrong") == "Fixed the timer, it was wrong"
    assert voice.tidy("It’s the “export” job") == "It's the \"export\" job"


def test_the_offence_is_reported_as_he_would_read_it():
    """The list holds stems so one entry catches a whole family, but a retry
    saying "you used 'leverag'" is worse feedback than one saying 'leveraged'."""
    from src import voice
    assert "leveraged" in voice.offences(["We leveraged it"])
    assert "leveraging" in voice.offences(["Leveraging the bus"])
    assert "leverag" not in voice.offences(["We leveraged it"])


# ------------------------------------------------- documents are held to it

class Backend:
    model = "fake"
    def __init__(self, *replies):
        self.replies, self.asked = list(replies), []
    def _ask(self, parts, schema=None):
        self.asked.append(parts[0]["text"])
        return self.replies.pop(0) if self.replies else "{}"


def _doc(*blocks, title="Tent logbook"):
    return json.dumps({"title": title, "blocks": list(blocks)})


def test_a_document_is_asked_again_and_told_exactly_what_was_wrong():
    from src import documents
    bad = _doc({"type": "paragraph",
                "text": "We leveraged a robust approach to streamline the build."},
               {"type": "bullets", "items": ["**Blockers:** waiting on the firmware"]})
    good = _doc({"type": "paragraph",
                 "text": "We used hardware pull-up resistors on the I2C bus."})
    backend = Backend(bad, good)
    cfg.config.PIPELINE = "gemini"
    try:
        out = documents.compose("make me a doc", backend=backend)
    finally:
        cfg.config.PIPELINE = "stub"

    assert len(backend.asked) == 2, "it did not ask again"
    retry = backend.asked[1].lower()
    for named in ("leveraged", "robust", "streamline", "bolded label"):
        assert named in retry, f"{named} was not named in the retry: {retry[-300:]}"
    assert "pull-up resistors" in out["blocks"][0]["text"]


def test_a_command_in_a_document_never_triggers_a_retry():
    """A code block is not prose and must not be read as though it were."""
    from src import documents
    doc = _doc({"type": "paragraph", "text": "Run this to list the bus."},
               {"type": "code", "text": "i2cdetect -y 1; make robust-build --delve"})
    backend = Backend(doc)
    cfg.config.PIPELINE = "gemini"
    try:
        out = documents.compose("make me a doc", backend=backend)
    finally:
        cfg.config.PIPELINE = "stub"
    assert len(backend.asked) == 1, "a code block sent it back for a rewrite"
    code = [b for b in out["blocks"] if b["type"] == "code"][0]
    assert code["text"] == "i2cdetect -y 1; make robust-build --delve", "code was rewritten"


def test_table_rows_keep_their_punctuation():
    """A row of readings is data. Rewriting its separators corrupts it."""
    from src import documents
    doc = documents.normalise({"title": "Bus", "blocks": [
        {"type": "table", "columns": ["Sensor", "Address"],
         "rows": [["EZO HUM", "0x27; alt 0x28"], ["Range", "0 — 100 %RH"]]}]})
    out = documents.enforce(doc)
    rows = out["blocks"][0]["rows"]
    assert rows[0][1] == "0x27; alt 0x28"
    assert rows[1][1] == "0 — 100 %RH"


def test_the_tics_are_rewritten_even_when_the_model_will_not_stop():
    """After asking twice, the typography is put right mechanically. Words are
    left alone, because deleting a sentence changes what the document says."""
    from src import documents
    stubborn = _doc({"type": "bullets",
                     "items": ["**Blockers:** high humidity — sensor drift"]})
    backend = Backend(stubborn, stubborn)
    cfg.config.PIPELINE = "gemini"
    try:
        out = documents.compose("make me a doc", backend=backend)
    finally:
        cfg.config.PIPELINE = "stub"
    assert out["blocks"][0]["items"] == ["Blockers: high humidity, sensor drift"]


def test_a_retry_that_reads_worse_is_not_kept():
    """Second is not the same as better."""
    from src import documents
    first = _doc({"type": "paragraph", "text": "We used a robust approach."})
    worse = _doc({"type": "paragraph",
                  "text": "We leveraged a robust, seamless, holistic deep dive. 🚀"})
    backend = Backend(first, worse)
    cfg.config.PIPELINE = "gemini"
    try:
        out = documents.compose("make me a doc", backend=backend)
    finally:
        cfg.config.PIPELINE = "stub"
    assert "leveraged" not in out["blocks"][0]["text"]


def test_the_weekly_note_and_the_documents_share_one_rule():
    """Two copies of a rule is one rule and one bug waiting."""
    from src import weeknote, voice
    assert weeknote.BANNED is voice.BANNED
    assert weeknote.offences is voice.offences
