"""Which model answers, and where the words go.

The thing being protected here is not quality, it is that ENYGMA is holding his
brother's employer's material. Local never leaves the Spark; the other two do.
Every test below is about that distinction being real, visible, and impossible
to get wrong by accident.

The Spark is not reachable from a test run, so the ollama client is exercised
against a stand-in that speaks the real wire format: the canned answers are
fake, the request shape, schema passing, image encoding and error codes are not.
"""
import os, sys, json, pathlib, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
os.environ.setdefault("ENYGMA_SESSION_SECRET", "test-secret")
os.environ.setdefault("ENYGMA_INSECURE_COOKIES", "1")

from src import db, config as cfg                # noqa: E402
from src.ingest import upload                    # noqa: E402

SEEN = []          # every request the fake received, so the client can be checked


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._json(200, {"models": [
                {"name": "qwen3.6:35b", "size": 22621314381,
                 "details": {"parameter_size": "35.5B"},
                 "capabilities": ["completion", "tools", "thinking", "vision"]}]})
        self._json(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(
            int(self.headers.get("content-length", 0))) or b"{}")
        SEEN.append(body)
        if body.get("model") == "not-pulled":
            return self._json(404, {"error": "model not found"})
        if body.get("format"):
            content = json.dumps({"title": "Tent logbook", "blocks": [
                {"type": "paragraph", "text": "The rail carries the ESP32."}]})
        elif body["messages"][0].get("images"):
            content = "<think>looking</think>The jumper is in the wrong column."
        else:
            content = "<think>weighing it</think>Use 4.7k pull-ups on both lines."
        if body.get("stream"):
            return self._ndjson(content)
        self._json(200, {"message": {"role": "assistant", "content": content}})

    def _ndjson(self, content):
        """The real wire format: one JSON object per line, split at awkward
        places on purpose. A tag broken across two chunks is the case the
        streaming filter exists for, so the fake must produce one."""
        self.send_response(200)
        self.send_header("content-type", "application/x-ndjson")
        self.end_headers()
        step = 7
        for at in range(0, len(content), step):
            self.wfile.write(json.dumps(
                {"message": {"role": "assistant", "content": content[at:at + step]},
                 "done": False}).encode() + b"\n")
            self.wfile.flush()
        self.wfile.write(json.dumps({"message": {"content": ""}, "done": True}).encode() + b"\n")
        self.wfile.flush()

    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


_server = None


def setup_module(_):
    global _server
    tmp = pathlib.Path(tempfile.mkdtemp())
    cfg.DB_PATH = tmp / "t.db"; cfg.DATA_DIR = tmp
    db.DB_PATH = cfg.DB_PATH;  db.DATA_DIR = cfg.DATA_DIR
    upload.UPLOADS = tmp / "uploads"; upload.BASE_DIR = tmp
    db.migrate()
    _server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
    cfg.config.OLLAMA_HOST = f"http://127.0.0.1:{_server.server_port}"
    cfg.config.OLLAMA_MODEL = "qwen3.6:35b"


def teardown_module(_):
    if _server:
        _server.shutdown()


# ------------------------------------------------------------ the local one

def test_the_local_model_answers():
    from src.pipeline.ollama import OllamaBackend
    assert OllamaBackend().ask("Why pull-ups?") == "Use 4.7k pull-ups on both lines."


def test_reasoning_is_not_the_answer():
    """These models think out loud. It is interesting and it is not what he
    asked for, so it comes off the front."""
    from src.pipeline.ollama import _without_thinking
    assert _without_thinking("<think>hmm</think>Use 4.7k.") == "Use 4.7k."
    # Cut off mid-thought: everything after the tag is reasoning, none of it
    # is an answer, and showing half a thought is worse than showing nothing.
    assert _without_thinking("Here it is. <think>now let me").strip() == "Here it is."
    assert _without_thinking("<thinking>a</thinking>b") == "b"


def test_an_image_is_sent_as_base64_the_way_ollama_wants_it():
    import base64
    from src.pipeline.ollama import OllamaBackend
    SEEN.clear()
    reply = OllamaBackend().ask("What is wrong here?", images=[b"\x89PNG-not-really"])
    assert "jumper" in reply
    sent = SEEN[-1]["messages"][0]["images"][0]
    assert base64.b64decode(sent) == b"\x89PNG-not-really"
    assert not sent.startswith("data:"), "ollama wants bare base64, not a data URL"


def test_a_schema_is_passed_through_as_a_format():
    from src.pipeline.ollama import OllamaBackend
    SEEN.clear()
    out = OllamaBackend().ask("Make a doc", schema={"type": "object"})
    assert SEEN[-1]["format"] == {"type": "object"}
    assert json.loads(out)["title"] == "Tent logbook"


def test_a_missing_model_says_how_to_fix_it():
    """The fix is one command on his own machine, so the error should be that
    command rather than a status code."""
    import pytest
    from src.pipeline.ollama import OllamaBackend, OllamaError
    with pytest.raises(OllamaError) as raised:
        OllamaBackend(model="not-pulled").ask("hello")
    assert "ollama pull not-pulled" in str(raised.value)


def test_ollama_being_down_is_reported_before_he_types_into_it():
    from src.pipeline.ollama import OllamaBackend
    ready, why = OllamaBackend(host="http://127.0.0.1:1").available()
    assert ready is False
    assert "cannot reach ollama" in why


# ------------------------------------------------------- choosing, and where

def test_the_picker_says_where_the_words_go():
    """The only place the interface ever puts this question to him."""
    from src import models
    assert models.NOTES["local"] == "Never leaves the Spark"
    assert "Google" in models.NOTES["gemini"]
    assert "Anthropic" in models.NOTES["opus"]


def test_a_model_with_no_key_is_offered_but_marked_not_ready():
    from src import models
    for name in ("ENYGMA_GEMINI_API_KEY", "ENYGMA_ANTHROPIC_API_KEY"):
        os.environ.pop(name, None)
    by_key = {m["key"]: m for m in models.offered()}
    assert by_key["gemini"]["ready"] is False and by_key["gemini"]["why"]
    assert by_key["opus"]["ready"] is False
    assert by_key["local"]["ready"] is True, "the fake ollama should be reachable"


def test_the_default_is_the_one_that_does_not_leave_the_building():
    from src import models
    assert models.default() == "local"


def test_an_unknown_name_falls_back_rather_than_failing():
    from src import models
    assert models.resolve("gpt-9") == "local"
    assert models.resolve(None) == "local"
    assert models.resolve("opus") == "opus"


def test_the_choice_belongs_to_the_thread_and_survives():
    """Per thread, not per message: Chat has memory, and half a conversation
    reasoned by one model and half by another is a conversation neither of them
    is really having."""
    from src import chat
    a, b = chat.start("One"), chat.start("Two")
    assert chat.model_of(a) == "local"
    chat.set_model(a, "opus")
    assert chat.model_of(a) == "opus"
    assert chat.model_of(b) == "local", "it leaked into another thread"


def test_a_thread_that_never_chose_follows_the_default():
    """NULL means "whatever the default is now", so changing the default moves
    every thread he never had an opinion about and leaves the rest alone."""
    from src import chat, models
    opinionated, quiet = chat.start("Chose"), chat.start("Did not")
    chat.set_model(opinionated, "gemini")
    was = cfg.config.CHAT_DEFAULT
    try:
        cfg.config.CHAT_DEFAULT = "opus"
        assert chat.model_of(quiet) == "opus"
        assert chat.model_of(opinionated) == "gemini"
    finally:
        cfg.config.CHAT_DEFAULT = was


def test_opus_without_a_key_refuses_in_a_sentence():
    import pytest
    from src.pipeline.anthropic import AnthropicBackend, AnthropicError
    was = cfg.config.ANTHROPIC_API_KEY
    try:
        cfg.config.ANTHROPIC_API_KEY = ""
        with pytest.raises(AnthropicError) as raised:
            AnthropicBackend(api_key="")._ask([{"type": "text", "text": "hi"}])
        assert "ENYGMA_ANTHROPIC_API_KEY" in str(raised.value)
    finally:
        cfg.config.ANTHROPIC_API_KEY = was


def test_stub_mode_overrides_the_picker_entirely():
    """ENYGMA_PIPELINE=stub means the whole app runs with no key and no network.
    A local model is still a network call to another process, so stub mode has
    to short-circuit the picker rather than sit beside it."""
    from src import chat
    was = cfg.config.PIPELINE
    try:
        cfg.config.PIPELINE = "stub"
        SEEN.clear()
        thread = chat.start("Quiet")
        chat.set_model(thread, "local")
        chat.say(thread, "Why do I need pull-up resistors?")
        assert SEEN == [], "stub mode still called out to ollama"
    finally:
        cfg.config.PIPELINE = was


def test_the_picker_does_not_dial_ollama_on_every_page_render():
    """Uncached, a stopped ollama turned every chat page load into a four second
    wait: the suite went from eight seconds to twenty, which is how this was
    found. A page render must not pay for a network round trip it just paid."""
    import time
    from src import models
    models.forget_readiness()
    models.offered()                       # warms it
    started = time.monotonic()
    for _ in range(50):
        models.offered()
    spent = time.monotonic() - started
    assert spent < 0.5, f"50 renders took {spent:.2f}s; the check is not cached"


def test_a_stopped_ollama_does_not_hang_the_page():
    from src import models, config as c
    was = c.config.OLLAMA_HOST
    try:
        c.config.OLLAMA_HOST = "http://127.0.0.1:1"   # nothing listening
        models.forget_readiness()
        import time
        started = time.monotonic()
        by_key = {m["key"]: m for m in models.offered()}
        assert time.monotonic() - started < 4.0
        assert by_key["local"]["ready"] is False
        assert by_key["local"]["why"], "it should say why, not just fail"
    finally:
        c.config.OLLAMA_HOST = was
        models.forget_readiness()


# ------------------------------------------------------------- streaming

def test_the_local_model_streams_the_same_answer_it_would_have_said():
    """Streaming must not become a second, differently-behaved client. Same
    request shape, same answer, delivered in pieces."""
    from src.pipeline.ollama import OllamaBackend
    SEEN.clear()
    pieces = list(OllamaBackend().stream([{"type": "text", "text": "Why pull-ups?"}]))
    assert SEEN[-1]["stream"] is True
    assert len(pieces) > 1, "it came in one lump, which is not streaming"
    assert "".join(pieces) == "Use 4.7k pull-ups on both lines."


def test_reasoning_is_stripped_out_of_a_stream_it_cannot_see_the_end_of():
    """The fake cuts the content every seven characters, so <think> arrives in
    two pieces. A filter that only looks at one chunk at a time shows him the
    model's private reasoning."""
    from src.pipeline.ollama import OllamaBackend
    out = "".join(OllamaBackend().stream([{"type": "text", "text": "Why pull-ups?"}]))
    assert "weighing" not in out and "<think" not in out


def test_a_stream_that_stops_mid_thought_yields_nothing_rather_than_reasoning():
    from src.pipeline.ollama import Unthink
    filter_ = Unthink()
    shown = "".join(filter_.feed(c) for c in ["The answer. <thi", "nk>now let me"])
    assert filter_.close() == "", "the reasoning was flushed as if it were an answer"
    assert shown == "The answer. "


def test_a_lone_angle_bracket_is_not_held_back_forever():
    """'a < b' is arithmetic, not the start of a tag, and it has to come out."""
    from src.pipeline.ollama import Unthink
    filter_ = Unthink()
    assert filter_.feed("if a < b then") + filter_.close() == "if a < b then"


def test_a_stream_that_is_never_read_to_the_end_closes_the_connection():
    """What the stop button does: there is no cancel API, closing the socket is
    the cancel. The generator must be safe to abandon."""
    from src.pipeline.ollama import OllamaBackend
    stream = OllamaBackend().stream([{"type": "text", "text": "Why pull-ups?"}])
    assert next(stream)
    stream.close()          # must not raise


# ------------------------------------------------ the paid one, streaming

class _Anthropic(BaseHTTPRequestHandler):
    """Anthropic's server-sent events, in the shape the real one sends them:
    usage split across message_start and message_delta, text in deltas."""

    def log_message(self, *a):
        pass

    def do_POST(self):
        json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for event in (
            {"type": "message_start", "message": {"usage": {"input_tokens": 812}}},
            {"type": "content_block_delta", "delta": {"type": "text_delta",
                                                      "text": "Use 4.7k "}},
            {"type": "content_block_delta", "delta": {"type": "text_delta",
                                                      "text": "pull-ups."}},
            {"type": "message_delta", "usage": {"output_tokens": 64}},
            {"type": "message_stop"},
        ):
            self.wfile.write(b"event: x\n data\n".replace(b" data\n", b""))
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.flush()


def test_opus_streams_and_bills_what_it_actually_generated():
    """Usage is read as it arrives, not at the end, so an answer he stops
    halfway is still billed. Anthropic generated those tokens whether or not he
    read them, and a stopped answer showing up as free would make the running
    total on Home wrong in the direction that matters."""
    from src.pipeline.anthropic import AnthropicBackend
    server = HTTPServer(("127.0.0.1", 0), _Anthropic)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        backend = AnthropicBackend(api_key="k")
        backend.API = f"http://127.0.0.1:{server.server_port}/v1/messages"
        pieces = []
        for piece in backend.stream([{"type": "text", "text": "why?"}]):
            pieces.append(piece)
            if len(pieces) == 1:
                break               # stopped after the first chunk
        assert pieces == ["Use 4.7k "]
        assert backend.usage["input"] == 812, "the input tokens were never recorded"
    finally:
        server.shutdown()


def test_the_streaming_and_blocking_calls_ask_for_the_same_thing():
    """Two code paths to one API is two chances to drift. They share the body."""
    from src.pipeline.anthropic import AnthropicBackend
    backend = AnthropicBackend(api_key="k")
    parts = [{"type": "text", "text": "why?"}]
    assert backend._body(parts) == {k: v for k, v in
                                    dict(backend._body(parts), stream=True).items()
                                    if k != "stream"}
