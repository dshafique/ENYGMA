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
    """The in-flight guard, and the field cleared before the request goes out, so
    a second press has nothing left to resend."""
    js = (pathlib.Path(__file__).resolve().parent.parent
          / "src/static/js/app.js").read_text()
    chat_block = js[js.index("-------- chat */"):js.index("------- settings */")]
    assert "if (sending) return;" in chat_block
    assert "body.disabled = true" in chat_block
    # Cleared before the await, not after it.
    cleared = chat_block.index('body.value = "";')
    awaited = chat_block.index("await send(form.action")
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
