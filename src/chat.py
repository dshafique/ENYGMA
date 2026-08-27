"""Chat.

Chat is the place, ENYGMA is the who. A thread can start empty or from a term he
held down in a transcript, and the term arrives as the first question so the
conversation has somewhere to go.

When no model is reachable the reply says so rather than inventing an answer. A
glossary hit is still returned, because that is real knowledge the app has.
"""
from .db import cursor
from . import glossary
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


def say(thread_id: int, body: str) -> dict:
    """One turn. His message in, one reply out."""
    body = (body or "").strip()
    if not body:
        raise ValueError("Nothing to send")
    _append(thread_id, "operator", body)
    _title_from_first(thread_id, body)
    reply = _answer(body, caveat=_first_reply(thread_id))
    _append(thread_id, "enygma", reply)
    return {"reply": reply}


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


def _answer(question: str, caveat: bool = True) -> str:
    hit = glossary.lookup(_probable_term(question))
    if config.PIPELINE != "gemini":
        if hit:
            return f"{hit['term']} — {hit['gloss']}" + (f"\n\n{NO_MODEL}" if caveat else "")
        return NO_MODEL if caveat else "That one is not in my glossary yet."
    try:
        from .pipeline.gemini import GeminiBackend
        backend = GeminiBackend()
        prompt = (
            "You are ENYGMA, answering one question for an engineering intern. "
            "Be direct and concrete. Three short paragraphs at most. If you are "
            "not sure, say so.\n\nQuestion: " + question
        )
        if hit:
            prompt += f"\n\nThe app's own glossary says: {hit['gloss']}"
        return backend._ask([{"type": "text", "text": prompt}]).strip()
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
