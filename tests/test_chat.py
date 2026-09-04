"""Chat as a conversation, not four monologues.

Written from a real failure: on a phone he reached for a new line, the return
key sent instead, and the same half-finished sentence was answered four times
with four unrelated essays. Three separate defects behind one screenshot --
Return sending where there is no Shift to hold, no guard against a resend, and
a prompt that never carried the thread -- so three separate tests.
"""
import os, sys, pathlib, tempfile, re

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


def test_the_same_sentence_twice_is_one_turn_not_two():
    """The exact shape of the bug: four presses, four identical messages, four
    answers. A resend inside the window returns what was already said."""
    from src import chat
    thread_id = chat.start("New conversation")
    chat.say(thread_id, "I want to keep track of the work I do.")
    first = chat.thread(thread_id)

    for _ in range(3):
        chat.say(thread_id, "I want to keep track of the work I do.")

    after = chat.thread(thread_id)
    assert len(after["messages"]) == len(first["messages"]) == 2, (
        "a repeated press wrote a new turn: "
        f"{[m['body'][:30] for m in after['messages']]}"
    )


def test_a_different_question_is_still_a_new_turn():
    """The duplicate guard must not swallow a real second question."""
    from src import chat
    thread_id = chat.start("New conversation")
    chat.say(thread_id, "What is a retained message?")
    chat.say(thread_id, "And what breaks if I do not set it?")
    messages = chat.thread(thread_id)["messages"]
    assert len(messages) == 4, [m["body"][:40] for m in messages]
    assert messages[2]["body"] == "And what breaks if I do not set it?"


def test_the_thread_is_carried_into_the_prompt():
    """A follow-up has to follow something. Before this, every turn was answered
    cold, which is why 'what about the second one?' had no answer to give."""
    from src import chat
    thread_id = chat.start("New conversation")
    chat.say(thread_id, "What is a retained message?")
    history = chat._history(thread_id)
    assert [t["role"] for t in history] == ["operator", "enygma"]

    transcript = chat._transcript(history)
    assert "Operator: What is a retained message?" in transcript
    assert "ENYGMA:" in transcript


def test_history_is_bounded():
    """A long thread must not grow the prompt without limit."""
    from src import chat
    thread_id = chat.start("New conversation")
    for n in range(10):
        chat.say(thread_id, f"Question number {n}, which is not like the others.")
    assert len(chat._history(thread_id, turns=6)) == 6


def test_return_does_not_send_where_there_is_no_shift_key():
    """The composer sends on Return only on a device that has a Shift key to hold
    for a new line. On a touch keyboard, Return returns."""
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat_block = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert "(hover: hover) and (pointer: fine)" in chat_block
    assert "keyboardSends" in chat_block
    assert "e.isComposing" in chat_block, "an IME's Enter must not send either"


def test_the_composer_cannot_fire_twice():
    """A second press while an answer is coming must never start a second turn.

    It used to return and do nothing. Now it stops the answer, which is what the
    button says it does at that moment -- but the thing being guarded is the
    same: whatever a second press means, it is not another turn. And the field
    is still cleared before the request goes out, so there is nothing left in it
    for a stray press to resend."""
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat_block = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert "if (sending) {" in chat_block
    guard = chat_block.index("if (sending) {")
    # The stop branch must return before anything that could send a message.
    branch = chat_block[guard:guard + 400]
    assert "/stop`" in branch and "return;" in branch
    assert "/stream`" not in branch, "a second press can still start a turn"
    # Cleared before the await, not after it.
    cleared = chat_block.index('body.value = "";')
    awaited = chat_block.index("await send(`/chat/${threadId}/stream`")
    assert cleared < awaited, "the field is still holding the text during the request"


def test_a_failed_send_gives_him_his_words_back():
    """Losing what he typed is worse than the error itself."""
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat_block = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert "const restore = ()" in chat_block
    assert "body.value = text;" in chat_block


def test_the_phone_is_told_that_return_is_safe():
    """The rule is only useful if it is visible on the surface it applies to."""
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/chat.html").read_text()
    assert "composer-hint" in html
    assert "Return starts a new line" in html


def test_the_installer_does_not_call_a_live_pipeline_a_stub():
    """It ended by telling him the pipeline was still the stub while its own env
    report, four lines above, showed gemini and a key. Advice that contradicts
    the evidence on the same screen is how a working install gets 'fixed'."""
    import subprocess, tempfile, os
    root = pathlib.Path(__file__).resolve().parent.parent
    script = (root / "deploy/install-on-spark.sh").read_text()
    block = script[script.index("PIPELINE_NOW="):script.index("cat <<EOF")]

    def decide(env_text: str) -> str:
        tmp = pathlib.Path(tempfile.mkdtemp())
        (tmp / ".env").write_text(env_text)
        out = subprocess.run(
            ["bash", "-c", f'APP_DIR="{tmp}"\n{block}\nprintf "%s" "$PIPELINE_STEP"'],
            capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        return out.stdout

    live = decide("ENYGMA_PIPELINE=gemini\nENYGMA_GEMINI_API_KEY=AIzaSyNotARealKey\n")
    assert "still the stub" not in live and "the stub" not in live
    assert "Nothing to change" in live

    keyless = decide("ENYGMA_PIPELINE=gemini\nENYGMA_GEMINI_API_KEY=\n")
    assert "empty" in keyless, keyless

    stub = decide("ENYGMA_PIPELINE=stub\n")
    assert "the stub" in stub and "ENYGMA_PIPELINE=gemini" in stub


# --------------------------------------------------------------- the Fold

def _css() -> str:
    return (pathlib.Path(__file__).resolve().parent.parent
            / "src/static/css/app.css").read_text()


def test_the_writing_bar_sticks_to_the_screen_not_to_the_transcript():
    """Reported as "the writing bar doesn't fit the phone". It fitted; it was
    below the fold. The composer was an ordinary block at the end of a growing
    page, so four answers pushed it out of sight and reaching it meant scrolling
    the whole conversation."""
    css = _css()
    block = css[css.index(".composer {"):css.index(".composer form {")]
    assert "position: sticky" in block
    # Offset by the measured keyboard rather than pinned to a viewport bottom
    # that some browsers never move.
    assert "bottom: var(--kb, 0px)" in block


def test_the_composer_clears_the_tab_bar_on_a_phone():
    """Sticking to 0 on mobile parks it underneath the fixed tab bar."""
    css = _css()
    phone = css[css.index("@media (max-width: 899px) {\n  .chatwrap"):]
    phone = phone[:phone.index("@media (max-width: 380px)")]
    assert "var(--tabbar)" in phone and "env(safe-area-inset-bottom)" in phone
    assert "var(--kb, 0px)" in phone, "it does not clear the keyboard"


def test_the_send_button_cannot_be_squeezed_off_a_narrow_screen():
    """A flex item will not shrink below its intrinsic width unless told to, and
    a textarea's intrinsic width comes from its cols attribute. That is what
    pushes the button off the edge of a 344px cover screen."""
    css = _css()
    assert ".composer textarea { min-width: 0; }" in css
    assert ".composer form > .btn { flex: none; }" in css


def test_the_cover_screen_width_is_written_down():
    """He should not have to report this twice."""
    css = _css()
    assert "344" in css and "Fold" in css


def test_the_keyboard_shrinks_the_layout_not_just_the_view():
    """Without this, 100dvh still counts the space the keyboard covers and a bar
    stuck to the bottom of the screen is stuck behind the keyboard."""
    html = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/base.html").read_text()
    assert "interactive-widget=resizes-content" in html


def test_the_tabs_get_out_of_the_way_while_he_types():
    """Six tabs are 60px. With a keyboard up on a cover screen there is not much
    more than a hundred to spend."""
    css, js = _css(), (pathlib.Path(__file__).resolve().parent.parent
                       / "src/static/js/app.js").read_text()
    assert "html.typing .tabbar { display: none; }" in css
    chat = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert 'classList.toggle("typing"' in chat
    # focusin/focusout on the whole composer, not focus/blur on the box: see
    # test_pressing_send_does_not_move_the_send_button for why that matters.
    assert '"focusin"' in chat and '"focusout"' in chat


def test_the_newest_answer_is_scrolled_to_on_a_phone_too():
    """On a phone the transcript is not its own scroller, the page is, so
    scrolling the element does nothing and the answer stays off screen."""
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert "window.scrollTo" in chat
    assert "convo.scrollHeight > convo.clientHeight" in chat


# ------------------------------------------------- a failure is not a fact

def test_a_failure_is_shown_to_him_but_never_taught_to_the_model():
    """Real, and he saw it. A document failed to save while the store was
    pointed at a read-only directory. The error was appended to the thread as an
    ENYGMA turn, and once Chat had memory every later answer read it back and
    reasoned from it: "Because my environment has a read-only file system limit,
    copy the raw text block above and save it yourself." The bug was fixed within
    the hour; the thread went on repeating it, because to the model it was simply
    something ENYGMA had said about itself.
    """
    import tempfile as _tf
    from src import chat, db as _db, config as _cfg
    from src.ingest import upload as _up
    tmp = pathlib.Path(_tf.mkdtemp())
    _cfg.DB_PATH = tmp / "t.db"; _cfg.DATA_DIR = tmp
    _db.DB_PATH = _cfg.DB_PATH; _db.DATA_DIR = _cfg.DATA_DIR
    _up.UPLOADS = tmp / "uploads"; _up.BASE_DIR = tmp
    _db.migrate()

    thread_id = chat.start("Tent build")
    chat._append(thread_id, "operator", "make me a file")
    chat._append(thread_id, "enygma",
                 "I could not build that markdown: [Errno 30] Read-only file system",
                 transient=True)
    chat._append(thread_id, "operator", "how should I log the sensors?")
    chat._append(thread_id, "enygma", "Keep one file per day under docs/.")

    # He still sees it.
    shown = [m["body"] for m in chat.thread(thread_id)["messages"]]
    assert any("Errno 30" in b for b in shown), "the error vanished from his screen"

    # The model never does.
    remembered = " ".join(t["body"] for t in chat._history(thread_id))
    assert "Errno 30" not in remembered, "the failure is still being taught"
    assert "Read-only" not in remembered
    assert "Keep one file per day" in remembered, "real turns were dropped too"


# ------------------------------------------------------- stopping an answer
#
# Chat used to be one blocking request per turn: press send, watch a still
# screen for however long the local model took, get the whole answer at once.
# Now it streams and Send becomes Stop. The tests below are about the half of
# that which can go wrong quietly -- what is kept, what is thrown away, and what
# the model is told about it next time.


class Streamer:
    """A backend that hands over one word at a time and counts how far it got."""
    model = "fake"

    def __init__(self, text="Use 4.7k pull-ups on both lines.", after=None):
        self.words = text.split(" ")
        self.given = 0
        self.after = after            # called with the count after each word
        self.asked = []

    def stream(self, parts, schema=None):
        self.asked.append(parts[0]["text"])
        for at, word in enumerate(self.words):
            self.given = at + 1
            yield word if at == 0 else " " + word
            if self.after:
                self.after(self.given)

    def _ask(self, parts, schema=None):
        self.asked.append(parts[0]["text"])
        return "Plainly said instead."


def _live(monkeyed):
    """Point chat at a given backend, with the pipeline switched on."""
    from src import models
    cfg.config.PIPELINE = "gemini"
    was = models.backend_for
    models.backend_for = lambda name=None: monkeyed
    return was


def _restore(was):
    from src import models
    models.backend_for = was
    cfg.config.PIPELINE = "stub"


def test_an_answer_arrives_in_pieces_and_is_stored_whole():
    from src import chat
    thread = chat.start("streaming")
    backend = Streamer()
    was = _live(backend)
    try:
        taken = chat.take(thread, "why pull-ups?")
        events = list(chat.reply(thread, taken["plan"]))
    finally:
        _restore(was)
    deltas = [e["delta"] for e in events if "delta" in e]
    done = [e["done"] for e in events if "done" in e]
    assert len(deltas) > 1, "it came in one lump"
    assert len(done) == 1, "exactly one done, always"
    assert "".join(deltas) == "Use 4.7k pull-ups on both lines."
    assert done[0]["reply"] == "Use 4.7k pull-ups on both lines."
    assert chat.thread(thread)["messages"][-1]["body"] == done[0]["reply"]


def test_stopping_keeps_what_had_already_arrived():
    """He presses stop when he has what he needed. Throwing the answer away at
    that moment would make the button useless."""
    from src import chat
    thread = chat.start("stopping")
    backend = Streamer(after=lambda n: chat.ask_to_stop(thread) if n == 3 else None)
    was = _live(backend)
    try:
        taken = chat.take(thread, "why pull-ups?")
        events = list(chat.reply(thread, taken["plan"]))
    finally:
        _restore(was)
    done = [e["done"] for e in events if "done" in e][0]
    assert done["stopped"] is True
    # One chunk more than he asked for, because the flag is read between chunks
    # and the model was already mid-word. That is the guarantee: within a chunk,
    # not instantly, and it stops rather than running to the end.
    assert done["reply"] == "Use 4.7k pull-ups on"
    assert backend.given == 4, "it kept generating long after being told to stop"
    stored = chat.thread(thread)["messages"][-1]
    assert stored["body"] == "Use 4.7k pull-ups on"
    assert stored["stopped"] == 1


def test_a_stopped_answer_is_marked_so_the_model_does_not_finish_the_sentence():
    """A fragment read back as a finished thought is how the next answer carries
    on from a claim nobody completed."""
    from src import chat
    line = chat._transcript([{"role": "enygma", "body": "Use 4.7k pull-ups",
                              "stopped": True}])
    assert "stopped you here" in line
    plain = chat._transcript([{"role": "enygma", "body": "Use 4.7k", "stopped": False}])
    assert "stopped you here" not in plain


def test_stopping_before_it_said_anything_stores_nothing():
    """An empty bubble in the thread is worse than no bubble."""
    from src import chat
    thread = chat.start("stopped at once")
    backend = Streamer()
    was = _live(backend)
    try:
        taken = chat.take(thread, "why pull-ups?")
        # Pressed while the server was still accepting the message, before a
        # single token existed. The browser cannot know how far it has got.
        chat.ask_to_stop(thread)
        events = list(chat.reply(thread, taken["plan"]))
    finally:
        _restore(was)
    done = [e["done"] for e in events if "done" in e][0]
    assert done["stopped"] is True and done.get("empty") is True
    roles = [m["role"] for m in chat.thread(thread)["messages"]]
    assert roles == ["operator"], "an empty answer was stored anyway"


def test_a_stopped_answer_is_not_rewritten_for_its_voice():
    """The rewrite exists to catch a model that ignored the prompt. A fragment
    he cut off mid-sentence has not ignored anything, and asking again would
    spend a second call to rewrite half a thought."""
    from src import chat
    thread = chat.start("no rewrite")
    backend = Streamer(text="We leveraged the robust pipeline here",
                       after=lambda n: chat.ask_to_stop(thread) if n == 3 else None)
    was = _live(backend)
    try:
        taken = chat.take(thread, "how did it go?")
        list(chat.reply(thread, taken["plan"]))
    finally:
        _restore(was)
    assert len(backend.asked) == 1, "it asked again about an answer he stopped"


def test_a_finished_answer_that_reads_like_a_machine_is_replaced_in_place():
    """It cannot be streamed -- the first attempt is already on screen -- so the
    rewrite arrives whole and takes its place."""
    from src import chat
    thread = chat.start("rewritten")
    backend = Streamer(text="We leveraged the robust pipeline here.")
    was = _live(backend)
    try:
        taken = chat.take(thread, "how did it go?")
        events = list(chat.reply(thread, taken["plan"]))
    finally:
        _restore(was)
    swapped = [e["replace"] for e in events if "replace" in e]
    assert swapped == ["Plainly said instead."]
    assert chat.thread(thread)["messages"][-1]["body"] == "Plainly said instead."


def test_his_message_is_saved_before_a_single_byte_is_streamed():
    """If the connection dies halfway through the answer, what he typed is still
    his and still there."""
    from src import chat
    thread = chat.start("saved first")
    was = _live(Streamer())
    try:
        chat.take(thread, "why pull-ups?")
        assert [m["body"] for m in chat.thread(thread)["messages"]] == ["why pull-ups?"]
    finally:
        _restore(was)


def test_abandoning_the_stream_still_keeps_what_the_model_said():
    """He closed the tab, the phone slept, the tunnel dropped. Nothing reached a
    yield after that, so without the fallback the answer would be lost -- and it
    really was said."""
    from src import chat
    thread = chat.start("abandoned")
    was = _live(Streamer())
    try:
        taken = chat.take(thread, "why pull-ups?")
        stream = chat.reply(thread, taken["plan"])
        next(stream); next(stream)
        stream.close()
    finally:
        _restore(was)
    stored = chat.thread(thread)["messages"][-1]
    assert stored["role"] == "enygma"
    assert stored["body"] == "Use 4.7k"
    assert stored["stopped"] == 1


def test_the_stop_flag_never_leaks_into_the_next_turn():
    """A flag left set would stop the following answer after one word, which
    would look like the model breaking rather than a stale bit of state."""
    from src import chat
    thread = chat.start("no leak")
    backend = Streamer(after=lambda n: chat.ask_to_stop(thread) if n == 2 else None)
    was = _live(backend)
    try:
        list(chat.reply(thread, chat.take(thread, "why pull-ups?")["plan"]))
        assert not chat.stop_wanted(thread)
        after = Streamer()
        from src import models
        models.backend_for = lambda name=None: after
        events = list(chat.reply(thread, chat.take(thread, "and the timing?")["plan"]))
    finally:
        _restore(was)
    assert [e["done"] for e in events if "done" in e][0]["stopped"] is False


def test_the_browser_cannot_swallow_the_stop_press():
    """A scar, and one only a browser could have found.

    The box is cleared the moment he presses Send. The same button is Stop while
    the answer writes itself. So when he pressed Stop, the browser ran its own
    validation on an empty required field, refused the submit, and showed
    "Please fill out this field" -- the handler never ran, the answer carried on,
    and the stop button did nothing at all. Every test passed.
    """
    page = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/chat.html").read_text()
    form = page[page.index('id="say"') - 200:page.index('id="say"') + 400]
    assert "novalidate" in form, "the browser will refuse the stop press again"
    assert "required" not in form, "an empty box blocks the button that stops"


def test_send_and_stop_are_one_button():
    """Two controls would be one more target to find on a folding phone, and
    every chat he has used puts Stop where Send was."""
    page = (pathlib.Path(__file__).resolve().parent.parent
            / "src/templates/chat.html").read_text()
    assert page.count('type="submit"') == 1
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat_block = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert 'sendBtn.setAttribute("aria-label", on ? "Stop" : "Send")' in chat_block, \
        "the button changes face without telling a screen reader"


def test_a_stream_is_written_as_text_never_as_markup():
    """It is model output going onto the page a character at a time. It goes on
    the same way a stored turn does."""
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat_block = js[js.index("-------- chat */"):js.index("------- settings */")]
    put = chat_block[chat_block.index("const put = (piece)"):]
    put = put[:put.index("};")]
    assert "textContent" in put and "innerHTML" not in put
