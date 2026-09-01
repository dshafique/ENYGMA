"""Chat.

Chat is the place, ENYGMA is the who. A thread can start empty or from a term he
held down in a transcript, and the term arrives as the first question so the
conversation has somewhere to go.

When no model is reachable the reply says so rather than inventing an answer. A
glossary hit is still returned, because that is real knowledge the app has.
"""
from .db import cursor
from . import glossary, library
from .config import config

NO_MODEL = (
    "I cannot reach a model yet, so this is everything I actually know. "
    "Set ENYGMA_PIPELINE=gemini and a key and I can go further than the glossary."
)


def threads() -> list[dict]:
    with cursor() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT t.*, "
            "  (SELECT body FROM chat_messages m WHERE m.thread_id = t.id "
            "   ORDER BY m.id DESC LIMIT 1) AS last_body, "
            "  (SELECT COUNT(*) FROM chat_messages m WHERE m.thread_id = t.id) AS messages "
            "FROM chat_threads t ORDER BY t.updated_at DESC, t.id DESC")]


def thread(thread_id: int) -> dict | None:
    with cursor() as conn:
        row = conn.execute("SELECT * FROM chat_threads WHERE id = ?", (thread_id,)).fetchone()
        if row is None:
            return None
        messages = [dict(m) for m in conn.execute(
            "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY id", (thread_id,))]
    return {"thread": dict(row), "messages": messages}


def start(title: str, seed_term: str | None = None,
          recording_id: int | None = None) -> int:
    with cursor() as conn:
        conn.execute(
            "INSERT INTO chat_threads (title, seed_term, recording_id) VALUES (?, ?, ?)",
            ((title or "New conversation").strip()[:120], seed_term, recording_id))
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def _append(thread_id: int, role: str, body: str) -> None:
    with cursor() as conn:
        conn.execute("INSERT INTO chat_messages (thread_id, role, body) VALUES (?, ?, ?)",
                     (thread_id, role, body))
        conn.execute("UPDATE chat_threads SET updated_at = datetime('now') WHERE id = ?",
                     (thread_id,))


# A resend of the same sentence inside this many seconds is a double-press, not
# a second question. The composer already guards against it; this is the net
# under that, for a flaky mobile connection retrying a request that in fact
# arrived.
DUPLICATE_SECONDS = 20


def say(thread_id: int, body: str) -> dict:
    """One turn. His message in, one reply out."""
    body = (body or "").strip()
    if not body:
        raise ValueError("Nothing to send")
    repeat = _recent_duplicate(thread_id, body)
    if repeat is not None:
        return {"reply": repeat, "duplicate": True}
    history = _history(thread_id)
    _append(thread_id, "operator", body)
    _title_from_first(thread_id, body)
    reply = _answer(body, caveat=_first_reply(thread_id), history=history)
    _append(thread_id, "enygma", reply)
    return {"reply": reply}


def _recent_duplicate(thread_id: int, body: str) -> str | None:
    """The same words again, seconds later. Answer with what was already said."""
    with cursor() as conn:
        row = conn.execute(
            "SELECT id, body, (julianday('now') - julianday(created_at)) * 86400.0 AS age "
            "FROM chat_messages WHERE thread_id = ? AND role = 'operator' "
            "ORDER BY id DESC LIMIT 1", (thread_id,)).fetchone()
        if row is None or row["body"] != body or (row["age"] or 0) > DUPLICATE_SECONDS:
            return None
        answer = conn.execute(
            "SELECT body FROM chat_messages WHERE thread_id = ? AND role = 'enygma' "
            "AND id > ? ORDER BY id LIMIT 1", (thread_id, row["id"])).fetchone()
    # The first press is still being answered; nothing to add by asking twice.
    return answer["body"] if answer else ""


def _history(thread_id: int, turns: int = 12) -> list[dict]:
    """What has already been said, oldest first, most recent turns only."""
    with cursor() as conn:
        rows = conn.execute(
            "SELECT role, body FROM chat_messages WHERE thread_id = ? "
            "ORDER BY id DESC LIMIT ?", (thread_id, turns)).fetchall()
    return [{"role": r["role"], "body": r["body"]} for r in reversed(rows)]


def _title_from_first(thread_id: int, body: str) -> None:
    """An untitled thread takes its name from what was actually asked."""
    with cursor() as conn:
        row = conn.execute("SELECT title FROM chat_threads WHERE id = ?",
                           (thread_id,)).fetchone()
        if row and row["title"] == "New conversation":
            conn.execute("UPDATE chat_threads SET title = ? WHERE id = ?",
                         (body.strip()[:60], thread_id))


def _first_reply(thread_id: int) -> bool:
    """The no-model caveat is worth saying once. Repeated every turn it is noise."""
    with cursor() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM chat_messages "
            "WHERE thread_id = ? AND role = 'enygma'", (thread_id,)).fetchone()
    return (row["n"] if row else 0) == 0


def _transcript(history: list[dict]) -> str:
    """The thread so far, as plain speech, so a follow-up has something to follow."""
    lines = []
    for turn in history:
        who = "Operator" if turn["role"] == "operator" else "ENYGMA"
        lines.append(f"{who}: {turn['body']}")
    return "\n\n".join(lines)


def _answer(question: str, caveat: bool = True,
            history: list[dict] | None = None) -> str:
    hit = glossary.lookup(_probable_term(question))
    found = library.context_for(question)

    if config.PIPELINE != "gemini":
        # No model: say what is actually known, and from where.
        parts = []
        if hit:
            parts.append(f"{hit['term']} — {hit['gloss']}")
        if found["sources"]:
            parts.append("From your library:\n\n" + found["text"])
        if caveat:
            parts.append(NO_MODEL)
        return "\n\n".join(parts) if parts else (
            NO_MODEL if caveat else "That is not in my glossary or your library.")
    try:
        from .pipeline.gemini import GeminiBackend
        backend = GeminiBackend()
        prompt = (
            "You are ENYGMA, answering an engineering intern in an ongoing "
            "conversation. Be direct and concrete. Three short paragraphs at "
            "most. If you are not sure, say so."
        )
        # Without this the thread had no memory: every turn was answered cold,
        # so "what about the second one?" was unanswerable and the same sentence
        # asked twice produced two unrelated essays instead of one thread.
        if history:
            prompt += (
                "\n\nThe conversation so far, oldest first. Do not repeat "
                "yourself; carry on from it, and read a short or elliptical "
                "message as a follow-up to what was already said:\n\n"
                + _transcript(history)
            )
        prompt += "\n\nOperator: " + question
        if hit:
            prompt += f"\n\nThe app's own glossary says: {hit['gloss']}"
        if found["text"]:
            prompt += (
                "\n\nThese passages are from the operator's own library. Prefer "
                "them over your general knowledge where they disagree, and say so "
                "if they do not answer the question:\n\n" + found["text"]
            )
        answer = backend._ask([{"type": "text", "text": prompt}], schema=None).strip()
        if found["sources"]:
            # Which documents were drawn on, so a claim can be traced.
            names = ", ".join(s["title"] for s in found["sources"])
            answer += f"\n\nDrawn from your library: {names}"
        return answer
    except Exception as exc:
        base = f"{hit['term']} — {hit['gloss']}\n\n" if hit else ""
        return base + f"I could not reach the model just now: {exc}"


def _probable_term(question: str) -> str:
    """The shortest useful guess: a quoted term, else the last two words."""
    text = (question or "").strip().strip("?")
    if '"' in text:
        parts = text.split('"')
        if len(parts) > 1 and parts[1].strip():
            return parts[1].strip()
    words = text.split()
    # Longest first: "retained message" should win over "message".
    for size in (3, 2, 1):
        if len(words) >= size:
            candidate = " ".join(words[-size:])
            if glossary.peek(candidate):
                return candidate
    return words[-1] if words else text
