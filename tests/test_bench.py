"""The bench, and what he brings to a conversation.

The backlog has two states because there are two people and one of them is
maintenance. What makes two states survivable is the note on the way out: six
weeks later, "crossed off" without a reason cannot tell them apart from "looked
at and turned down".
"""
import os, sys, pathlib, tempfile, io

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from src import db, config as cfg                # noqa: E402
from src.ingest import upload                    # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
       b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
       b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")


def setup_module(_):
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"; upload.BASE_DIR = tmp
    db.migrate()
    from src import attachments
    attachments.BASE_DIR = tmp
    attachments.DATA_DIR = tmp
    attachments.ATTACHED = tmp / "attached"


# ------------------------------------------------------------------ backlog

def test_an_entry_goes_on_and_comes_off():
    from src import bench
    e = bench.add("Humidity drifts 4% after an hour", "bug")
    assert e["kind"] == "bug" and e["done"] == 0
    assert bench.listing()["open"][0]["id"] == e["id"]

    bench.cross_off(e["id"], True, "pull-ups fixed it")
    after = bench.entry(e["id"])
    assert after["done"] == 1 and after["done_at"]
    assert after["note"] == "pull-ups fixed it"
    assert [x["id"] for x in bench.listing()["open"]] == []


def test_the_reason_is_what_makes_two_states_enough():
    """Without it, "crossed off" cannot tell "he fixed it" from "he decided
    against it", and in six weeks neither of them will remember."""
    from src import bench
    fixed = bench.add("Camera mount slips", "bug")
    declined = bench.add("Rebuild the admin screens", "idea")
    bench.cross_off(fixed["id"], True, "second screw held it")
    bench.cross_off(declined["id"], True, "not this quarter")
    notes = {e["id"]: e["note"] for e in bench.listing()["done"]}
    assert notes[fixed["id"]] != notes[declined["id"]]


def test_putting_something_back_forgets_why_it_was_closed():
    """A reopened entry carrying the reason it was closed the first time reads
    as though the decision still stands."""
    from src import bench
    e = bench.add("Fan schedule is wrong", "bug")
    bench.cross_off(e["id"], True, "not reproducible")
    bench.cross_off(e["id"], False)
    back = bench.entry(e["id"])
    assert back["done"] == 0 and back["note"] is None and back["done_at"] is None


def test_an_empty_entry_is_refused():
    import pytest
    from src import bench
    with pytest.raises(ValueError):
        bench.add("   ")


def test_an_unknown_kind_becomes_a_bug_rather_than_failing():
    from src import bench
    assert bench.add("Something", "nonsense")["kind"] == "bug"


# -------------------------------------------------------------------- notes

def test_a_note_names_itself_from_what_he_typed():
    """He is writing at a bench on a phone. A note he simply started typing into
    still has to have a name in the list."""
    from src import bench
    n = bench.new_note()
    assert n["title"] == "Untitled"
    bench.save_note(n["id"], None, "Resetting the EZO boards\n\nPower down first.")
    assert bench.note(n["id"])["title"] == "Resetting the EZO boards"


def test_a_title_he_set_is_not_overwritten_by_the_first_line():
    from src import bench
    n = bench.new_note()
    bench.save_note(n["id"], "Questions for Joseph", "Firmware build number.")
    bench.save_note(n["id"], "Questions for Joseph", "Firmware build number. And fans.")
    assert bench.note(n["id"])["title"] == "Questions for Joseph"


def test_the_preview_is_not_the_title_again():
    from src import bench
    n = bench.new_note()
    bench.save_note(n["id"], None, "Tent config\nESP32 on the rail over USB-C")
    found = next(x for x in bench.notes() if x["id"] == n["id"])
    assert found["title"] == "Tent config"
    assert found["preview"] == "ESP32 on the rail over USB-C"


def test_pinned_notes_come_first():
    from src import bench
    old = bench.new_note(); bench.save_note(old["id"], "Older", "a")
    new = bench.new_note(); bench.save_note(new["id"], "Newer", "b")
    bench.pin(old["id"], True)
    assert bench.notes()[0]["id"] == old["id"]


# --------------------------------------------------------------- attachments

def test_a_photo_is_kept_and_offered_to_the_model_as_an_image():
    from src import attachments, chat
    thread = chat.start("Bench")
    row = attachments.attach(thread, "board.png", PNG)
    assert row["kind"] == "image" and row["mime"] == "image/png"

    parts, described = attachments.parts_for([row])
    assert parts[0]["type"] == "image" and parts[0]["data"] == PNG
    assert "board.png" in described


def test_a_document_is_read_once_and_lands_in_the_library():
    """A datasheet is not something to look at once. It is something to be able
    to quote in three weeks."""
    from src import attachments, chat, library
    thread = chat.start("Bench")
    row = attachments.attach(thread, "ezo.txt",
                             b"The EZO humidity board answers at 0x27 by default.")
    assert row["kind"] == "file"
    assert "0x27" in row["extracted"]
    assert row["library_document_id"], "it never reached the Library"
    assert library.get(row["library_document_id"]) is not None

    # It reaches the model as text, not as a file it has to open.
    parts, _ = attachments.parts_for([row])
    assert parts[0]["type"] == "text" and "0x27" in parts[0]["text"]


def test_a_format_no_model_can_read_is_refused_with_a_sentence():
    """Samsung shoots JPEG, an iPhone does not, and answering about an image
    nobody could see is worse than refusing it."""
    import pytest
    from src import attachments, chat
    thread = chat.start("Bench")
    with pytest.raises(attachments.Refused) as raised:
        attachments.attach(thread, "photo.heic", b"not really heic")
    assert "JPEG" in str(raised.value)


def test_something_oversized_says_the_number():
    import pytest
    from src import attachments, chat
    thread = chat.start("Bench")
    with pytest.raises(attachments.Refused) as raised:
        attachments.attach(thread, "huge.png", b"x" * (attachments.MAX_BYTES + 1))
    assert "MB" in str(raised.value)


def test_a_file_waits_for_the_next_message_then_belongs_to_it():
    """Attach then type, not the reverse: the file has to survive him changing
    his mind about the wording."""
    from src import attachments, chat
    thread = chat.start("Bench")
    attachments.attach(thread, "board.png", PNG)
    assert len(attachments.pending(thread)) == 1

    was = cfg.config.PIPELINE
    try:
        cfg.config.PIPELINE = "stub"
        chat.say(thread, "What is wrong with this board?")
    finally:
        cfg.config.PIPELINE = was

    assert attachments.pending(thread) == [], "it never got tied to the message"
    messages = chat.thread(thread)["messages"]
    mine = [m for m in messages if m["role"] == "operator"][-1]
    assert [f["filename"] for f in attachments.for_message(mine["id"])] == ["board.png"]


def test_attachments_are_stored_where_the_service_can_write():
    """The unit grants two writable paths. A sibling directory is read-only at
    the kernel level however its permissions look."""
    src = (pathlib.Path(__file__).resolve().parent.parent / "src/attachments.py").read_text()
    assert 'ATTACHED = DATA_DIR / "attached"' in src


def test_what_he_attached_actually_reaches_the_model():
    """The bug this exists for looked completely correct from the outside. The
    image was stored, tied to the right message and shown back on screen. It
    just never went to the model, because the code that ties it to the message
    ran before the code that read what was waiting, so the list was empty by the
    time anybody asked."""
    from src import attachments, chat, models

    seen = {}

    class Watching:
        model = "fake"
        def _ask(self, parts, schema=None):
            seen["parts"] = parts
            return "I can see it."

    thread = chat.start("Bench")
    attachments.attach(thread, "board.png", PNG)

    was_pipeline, was_backend = cfg.config.PIPELINE, models.backend_for
    try:
        cfg.config.PIPELINE = "gemini"
        models.backend_for = lambda name: Watching()
        chat.say(thread, "What is wrong with this board?")
    finally:
        cfg.config.PIPELINE = was_pipeline
        models.backend_for = was_backend

    parts = seen.get("parts") or []
    images = [p for p in parts if p.get("type") == "image"]
    assert images, f"the model was handed no image: {[p.get('type') for p in parts]}"
    assert images[0]["data"] == PNG
    # And it is told there is one, so it answers about the thing rather than
    # around it.
    assert "attached" in parts[0]["text"]


# ------------------------------------------------------------------ filters

def test_the_list_can_be_narrowed_to_one_kind():
    from src import bench
    with db.cursor() as conn:
        conn.execute("DELETE FROM bench_entries")
    bench.add("Humidity drifts", "bug")
    bench.add("Log the CO2 curve", "idea")
    bench.add("Write the steps down", "todo")
    bench.add("Camera mount slips", "bug")

    assert len(bench.listing()["open"]) == 4
    only_bugs = bench.listing("bug")
    assert [e["kind"] for e in only_bugs["open"]] == ["bug", "bug"]
    assert only_bugs["kind"] == "bug"


def test_a_filter_never_hides_how_much_it_is_hiding():
    """A count that moves with the filter gives him no way to know what he is
    not looking at."""
    from src import bench
    with db.cursor() as conn:
        conn.execute("DELETE FROM bench_entries")
    bench.add("One", "bug"); bench.add("Two", "bug"); bench.add("Three", "idea")

    filtered = bench.listing("idea")
    assert len(filtered["open"]) == 1
    assert filtered["all_open"] == 3, "the total moved with the filter"
    assert filtered["tally"] == {"bug": 2, "idea": 1, "todo": 0}


def test_a_crossed_off_entry_does_not_count_as_open_in_the_tally():
    from src import bench
    with db.cursor() as conn:
        conn.execute("DELETE FROM bench_entries")
    one = bench.add("Fixed later", "bug")
    bench.add("Still open", "bug")
    bench.cross_off(one["id"], True, "done")
    assert bench.listing()["tally"]["bug"] == 1
    assert bench.listing()["all_open"] == 1


def test_a_nonsense_filter_shows_everything_rather_than_nothing():
    from src import bench
    with db.cursor() as conn:
        conn.execute("DELETE FROM bench_entries")
    bench.add("One", "bug")
    out = bench.listing("banana")
    assert out["kind"] is None and len(out["open"]) == 1


def test_the_add_form_does_not_look_like_a_filter():
    """The kind chips sat above the list looking exactly like the filter chips
    on the Meetings tab, so he tapped them expecting the list to filter and
    nothing happened. A control that looks like a filter and is not one is worse
    than no control."""
    css = (pathlib.Path(__file__).resolve().parent.parent
           / "src/static/css/app.css").read_text()
    block = css[css.index(".addbox {"):css.index(".addlabel")]
    assert "background: var(--surface)" in block
    assert "border:" in block

    html = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/backlog.html").read_text()
    assert 'class="filters benchfilters"' in html, "there are still no filters"
    # And they are links, so a filtered list is a place that survives a reload.
    assert 'href="/backlog?kind=' in html


def test_the_header_count_does_not_move_with_the_filter_either():
    """It said "2 open" under a Bug filter, one line above the tally that exists
    to stop exactly that."""
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/backlog.html").read_text()
    header = html[html.index('<header class="topbar">'):html.index("</header>")]
    assert "{{ all_open }} open" in header
    assert "open|length" not in header, "the header is counting the filtered list"
