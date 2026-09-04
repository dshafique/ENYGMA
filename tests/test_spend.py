"""What the paid models cost, counted here rather than discovered later.

ENYGMA cannot see the bill. Anthropic can, at the end of the month, and by then
it is spent. Two things this has to get right: the number, and how often it is
mentioned. A warning repeated on every answer for the rest of the month is one
he learns to scroll past, and the next one goes past with it.
"""
import os, sys, pathlib, tempfile

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


def _wipe():
    with db.cursor() as conn:
        conn.execute("DELETE FROM spend")
        conn.execute("DELETE FROM spend_warnings")


def test_the_arithmetic_matches_the_published_rate():
    """Opus at five dollars in and twenty-five out, per million."""
    from src import spend
    # A million in and a million out is thirty dollars.
    assert spend.price("anthropic", 1_000_000, 1_000_000) == 30 * spend.MILLICENTS
    assert spend.as_money(spend.price("anthropic", 200_000, 40_000)) == "$2.00"
    assert spend.as_money(spend.price("google", 1_000_000, 1_000_000)) == "$10.50"


def test_he_is_told_once_at_each_step_and_not_again():
    """The whole point. Repeating "you have passed ten dollars" on every answer
    for the rest of the month is how a warning becomes noise."""
    from src import spend
    _wipe()
    told = []
    for _ in range(60):
        out = spend.record("anthropic", "claude-opus-4-5", "chat", 40_000, 8_000)
        if out["step"]:
            told.append(spend.as_money(out["step"]))
    assert told == ["$10.00", "$20.00"], told


def test_the_message_says_the_step_and_the_running_total():
    from src import spend
    said = spend.notice("anthropic", 10 * spend.MILLICENTS, 1_234_567)
    assert "passed $10.00" in said
    assert "$12.35" in said
    # And it does not claim to be the invoice.
    assert "not the bill" in said


def test_local_costs_nothing_and_is_never_counted():
    from src import spend
    assert spend.PROVIDER_OF.get("local") is None
    assert spend.price("ollama", 999_999, 999_999) == 0


def test_a_call_that_reports_no_usage_is_not_guessed_at():
    """An invented number in a column labelled money is worse than no number."""
    from src import chat
    class Silent:
        model = "x"
    assert chat._bill(Silent(), "opus", "chat") is None
    class Empty:
        model = "x"; usage = {"input": 0, "output": 0}
    assert chat._bill(Empty(), "opus", "chat") is None


def test_the_same_tokens_are_not_billed_twice():
    """One backend object can answer twice when the voice rules ask again."""
    from src import chat, spend
    _wipe()
    class Once:
        model = "claude-opus-4-5"
        usage = {"input": 100_000, "output": 20_000}
    backend = Once()
    first = chat._bill(backend, "opus", "chat")
    second = chat._bill(backend, "opus", "chat")
    assert first is not None
    assert second is None, "it billed the same tokens again"
    assert spend.this_month("anthropic") == first["cost"]


def test_a_retry_is_billed_too_because_it_costs_money():
    from src import chat, spend
    _wipe()
    class Twice:
        model = "claude-opus-4-5"
        def __init__(self): self.usage = {"input": 100_000, "output": 20_000}
    backend = Twice()
    one = chat._bill(backend, "opus", "chat")
    backend.usage = {"input": 100_000, "output": 20_000}   # the second attempt
    two = chat._bill(backend, "opus", "chat")
    assert two is not None
    assert spend.this_month("anthropic") == one["cost"] + two["cost"]


def test_either_call_crossing_the_step_still_reports_it():
    from src import chat
    merged = chat._merge({"total": 1, "step": None}, {"total": 2, "step": 1_000_000})
    assert merged["step"] == 1_000_000
    merged = chat._merge({"total": 1, "step": 1_000_000}, {"total": 2, "step": None})
    assert merged["step"] == 1_000_000, "the first call's step was dropped"


def test_the_step_can_be_turned_off():
    from src import spend
    _wipe()
    was = cfg.config.SPEND_STEP_DOLLARS
    try:
        cfg.config.SPEND_STEP_DOLLARS = 0
        out = spend.record("anthropic", "m", "chat", 10_000_000, 2_000_000)
        assert out["step"] is None
        assert out["total"] > 0, "it should still count, just not interrupt"
    finally:
        cfg.config.SPEND_STEP_DOLLARS = was


def test_settings_shows_the_month_per_model():
    from src import spend
    _wipe()
    spend.record("anthropic", "claude-opus-4-5", "chat", 200_000, 40_000)
    spend.record("google", "gemini-3.5-flash", "document", 100_000, 20_000)
    rows = {r["provider"]: r for r in spend.summary()}
    assert rows["anthropic"]["money"] == "$2.00"
    assert rows["anthropic"]["calls"] == 1
    assert rows["google"]["input_tokens"] == 100_000


def test_every_call_is_kept_so_a_surprising_month_can_be_read_back():
    """A total is a number nobody can check."""
    from src import spend
    _wipe()
    for _ in range(5):
        spend.record("anthropic", "claude-opus-4-5", "chat", 1000, 200, thread_id=7)
    with db.cursor() as conn:
        rows = conn.execute("SELECT thread_id, what FROM spend").fetchall()
    assert len(rows) == 5
    assert all(r["thread_id"] == 7 and r["what"] == "chat" for r in rows)


def test_documents_are_billed_too():
    """They are the expensive calls. A total that quietly leaves them out is
    worse than no total, because he would trust it."""
    from src import made, spend, documents
    _wipe()

    class Paid:
        name = "gemini"; model = "gemini-3.5-flash"
        def __init__(self): self.usage = {"input": 0, "output": 0}
        def _ask(self, parts, schema=None):
            self.usage = {"input": 4000, "output": 1200}
            return '{"title": "Tent logbook", "blocks": [{"type": "paragraph", ' \
                   '"text": "The rail carries the ESP32."}]}'

    was = cfg.config.PIPELINE
    try:
        cfg.config.PIPELINE = "gemini"
        made.create("make me a .md file for the tent logbook", "md",
                    backend=Paid(), to_library=False)
    finally:
        cfg.config.PIPELINE = was

    with db.cursor() as conn:
        rows = conn.execute("SELECT what, provider FROM spend").fetchall()
    assert [r["what"] for r in rows] == ["document"]
    assert rows[0]["provider"] == "google"
    assert spend.this_month("google") > 0


def test_a_gemini_response_without_usage_does_not_crash_the_call():
    """The field has moved between versions of the SDK. An uncounted call leaves
    the total a little low, which is honest; a crash here would cost a
    transcription that already happened and already cost money."""
    from src.pipeline.gemini import _usage_of

    class Bare:
        pass
    assert _usage_of(Bare()) == {"input": 0, "output": 0}

    class Old:
        class usage_metadata:
            prompt_token_count = 1200
            candidates_token_count = 300
    assert _usage_of(Old()) == {"input": 1200, "output": 300}

    class Newer:
        class usage:
            input_tokens = 50
            output_tokens = 7
    assert _usage_of(Newer()) == {"input": 50, "output": 7}
