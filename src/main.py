"""ENYGMA — FastAPI skeleton.

Steps 3 to 5 of the build handoff: the app on its own port, its own database, its
own session, serving one page under the ENYGMA palette, with the passkey flow real
rather than stubbed.

Nothing here touches PHNTM. No cross-database queries, in either direction.
"""
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import config
from .db import migrate, cursor
from .auth import session, passkeys, attempts, secrets_store
from .ingest import poller, upload, notes as notes_ingest
from .pipeline import runner
from .export import as_markdown
from . import weeknote, documents
from . import made as made_repo
from . import (library, meetings as meetings_repo, actions as actions_repo,
               directory as directory_repo, chat as chat_repo, glossary,
               home as home_repo, fmt)

HERE = Path(__file__).resolve().parent
@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    glossary.seed_if_empty()
    runner.start()
    yield
    runner.stop()


# docs_url and friends are off: this app has one user and no public API surface.
app = FastAPI(title="ENYGMA", docs_url=None, redoc_url=None, openapi_url=None,
              lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.filters.update(fmt.FILTERS)
# Static assets are addressed by build. A browser that cached the previous
# stylesheet cannot serve it against this markup.
templates.env.globals["build"] = config.VERSION
templates.env.globals["mark_label"] = config.MARK
# Every page that renders an action needs the same set of states, in the same
# order, spelled the same way.
templates.env.globals["states"] = [
    (key, actions_repo.STATE_LABELS[key]) for key in actions_repo.STATES
]





# --------------------------------------------------------------------------
# session helpers
# --------------------------------------------------------------------------
def current(request: Request) -> dict | None:
    return session.read(request.cookies.get(session.cookie_name()))


def require_session(request: Request) -> dict:
    """A fresh session. For anything that changes state.

    Two different 401s, two different screens.

    reason=locked   -> the lock screen
    reason=stale    -> the compact re-auth sheet, so his place is kept
    """
    state = current(request)
    if state is None:
        raise HTTPException(status_code=401, detail={"reason": "locked"})
    if not state["fresh"]:
        raise HTTPException(status_code=401, detail={"reason": "stale"})
    return state


def require_view(request: Request) -> dict:
    """A session, fresh or not. For reading what the page is already showing.

    The line is: reading something already on screen needs a session; changing
    state needs a recent one. Holding a word in a transcript should not fail
    because he read the page five minutes ago, and being able to see a summary
    but not copy it is a distinction with no meaning behind it.
    """
    state = current(request)
    if state is None:
        raise HTTPException(status_code=401, detail={"reason": "locked"})
    return state


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    return "Good afternoon" if hour < 18 else "Good evening"


def page(request: Request, name: str, nav: str, extra: dict) -> HTMLResponse:
    """Every signed-in page goes through here so `nav` is never forgotten."""
    return templates.TemplateResponse(request, name, {"nav": nav, **extra})


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    with cursor() as conn:
        handle = conn.execute("SELECT handle FROM operator WHERE id = 1").fetchone()
    return page(request, "home.html", "home", {
        "d": home_repo.dashboard(),
        "week_note": home_repo.week_note(),
        "greeting": _greeting(),
        "handle": (handle["handle"] if handle else "there").title(),
        "today": datetime.now().strftime("%A %-d %B").upper(),
    })


@app.get("/lock", response_class=HTMLResponse)
def lock(request: Request):
    return templates.TemplateResponse(
        request,
        "lock.html",
        {
            "enrolled": passkeys.has_any_credential(),
            "lockout": attempts.lockout_remaining(),
            "has_pin": secrets_store.has_pin(),
        },
    )


# A service worker may only control the scope it is served from, and the
# manifest is read before there is any session, so both sit at the root.
@app.get("/sw.js")
def service_worker():
    return FileResponse(HERE / "static/sw.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-cache",
                                 "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(HERE / "static/manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/healthz")
def healthz():
    return {"ok": True, "app": "enygma", "port": config.PORT,
            "version": config.VERSION, "mark": config.MARK}


# --------------------------------------------------------------------------
# passkey registration
# --------------------------------------------------------------------------
@app.post("/auth/register/options")
def register_options(request: Request):
    # First enrolment is open; after that you must already be in.
    if passkeys.has_any_credential():
        require_session(request)
    token, options = passkeys.registration_options()
    payload = json.loads(options)
    payload["challengeToken"] = token
    return JSONResponse(payload)


@app.post("/auth/register/verify")
async def register_verify(request: Request):
    body = await request.json()
    token = body.get("challengeToken", "")
    device_name = body.get("deviceName", "This device")
    if passkeys.has_any_credential():
        require_session(request)
    try:
        passkeys.verify_registration(token, body.get("credential"), device_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    response = JSONResponse({"ok": True})
    session.set_on(response, session.issue())
    return response


# --------------------------------------------------------------------------
# passkey authentication
# --------------------------------------------------------------------------
@app.post("/auth/login/options")
def login_options():
    remaining = attempts.lockout_remaining()
    if remaining:
        raise HTTPException(status_code=429, detail={"lockout": remaining})
    token, options = passkeys.authentication_options()
    payload = json.loads(options)
    payload["challengeToken"] = token
    return JSONResponse(payload)


@app.post("/auth/login/verify")
async def login_verify(request: Request):
    remaining = attempts.lockout_remaining()
    if remaining:
        raise HTTPException(status_code=429, detail={"lockout": remaining})
    body = await request.json()
    try:
        passkeys.verify_authentication(body.get("challengeToken", ""), body.get("credential"))
    except Exception as exc:
        attempts.record("passkey", False)
        raise HTTPException(status_code=400, detail=str(exc))
    attempts.record("passkey", True)
    response = JSONResponse({"ok": True})
    session.set_on(response, session.issue())
    return response


# --------------------------------------------------------------------------
# pin fallback
# --------------------------------------------------------------------------
@app.post("/auth/pin/verify")
async def pin_verify(request: Request):
    remaining = attempts.lockout_remaining()
    if remaining:
        raise HTTPException(status_code=429, detail={"lockout": remaining})
    body = await request.json()
    if not secrets_store.verify_pin(str(body.get("pin", ""))):
        attempts.record("pin", False)
        raise HTTPException(status_code=400, detail="That PIN did not match")
    attempts.record("pin", True)
    response = JSONResponse({"ok": True})
    session.set_on(response, session.issue())
    return response


# --------------------------------------------------------------------------
# PIN management and setup codes
# --------------------------------------------------------------------------
@app.post("/auth/pin/set")
async def pin_set(request: Request):
    require_session(request)
    body = await request.json()
    try:
        secrets_store.set_pin(str(body.get("pin", "")))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/auth/pin/clear")
def pin_clear(request: Request):
    require_session(request)
    secrets_store.clear_pin()
    return {"ok": True}


@app.post("/auth/pairing/new")
async def pairing_new(request: Request):
    """A single-use code so a second device can enrol its own passkey.

    Requires a fresh session: this is the one credential that can create other
    credentials, so it is not something a left-open tab should be able to mint.
    """
    require_session(request)
    body = await request.json() if await request.body() else {}
    return secrets_store.create_pairing_code((body or {}).get("note"))


@app.post("/auth/pairing/redeem")
async def pairing_redeem(request: Request):
    """Redeemed on the NEW device, which then enrols its passkey."""
    remaining = attempts.lockout_remaining()
    if remaining:
        raise HTTPException(status_code=429, detail={"lockout": remaining})
    body = await request.json()
    device = str(body.get("deviceName") or "")[:60] or None
    if not secrets_store.consume_pairing_code(str(body.get("code", "")), device):
        attempts.record("pairing", False)
        raise HTTPException(status_code=400, detail="That setup code is not valid or has expired")
    attempts.record("pairing", True)
    response = JSONResponse({"ok": True})
    session.set_on(response, session.issue())
    return response


@app.post("/auth/logout")
def logout():
    response = JSONResponse({"ok": True})
    session.clear_on(response)
    return response


# --------------------------------------------------------------------------
# devices
# --------------------------------------------------------------------------
@app.get("/auth/devices")
def devices(request: Request):
    require_view(request)
    return {"devices": passkeys.enrolled_devices()}


@app.post("/auth/devices/{device_id}/revoke")
def revoke(device_id: int, request: Request):
    require_session(request)
    with cursor() as conn:
        conn.execute(
            "UPDATE credentials SET revoked_at = datetime('now') WHERE id = ?", (device_id,)
        )
    return {"ok": True}


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------
@app.get("/ingest/status")
def ingest_status(request: Request):
    require_view(request)
    return poller.status()


@app.post("/ingest/pull")
def ingest_pull(request: Request):
    require_session(request)
    return poller.pull_once()


# --------------------------------------------------------------------------
# meetings
# --------------------------------------------------------------------------
def _meetings_context(data=None) -> dict:
    return {
        "meetings": meetings_repo.listing(),
        "groups": meetings_repo.grouped(),
        "week_ms": meetings_repo.week_ms(),
        "max_mb": config.MAX_UPLOAD_MB,
        "pipeline": config.PIPELINE,
        "data": data,
    }


@app.get("/meetings", response_class=HTMLResponse)
def meetings_page(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    return page(request, "meetings.html", "meetings", _meetings_context())


@app.get("/api/meetings")
def meetings_api(request: Request):
    require_view(request)
    return {"meetings": meetings_repo.listing()}


@app.post("/upload")
async def upload_audio(request: Request, files: list[UploadFile] = File(...)):
    """Audio, or notes for a meeting nobody recorded. Same dropzone either way."""
    require_session(request)
    results = []
    for item in files:
        try:
            if notes_ingest.is_notes(item.filename):
                raw = await item.read()
                results.append({"filename": item.filename, "ok": True,
                                **notes_ingest.store(item.filename, raw)})
            else:
                results.append({"filename": item.filename, "ok": True, "kind": "audio",
                                **upload.store(item.filename, item.file)})
        except (upload.Rejected, library.Rejected) as exc:
            results.append({"filename": item.filename, "ok": False, "reason": str(exc)})
        finally:
            await item.close()
    return {"results": results}


@app.get("/meetings/{recording_id}", response_class=HTMLResponse)
def meeting_page(recording_id: int, request: Request):
    state = current(request)
    if state is None:
        return RedirectResponse("/lock", status_code=302)
    data = meetings_repo.detail(recording_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No such recording")
    return page(request, "meetings.html", "meetings", _meetings_context(data))


@app.get("/meetings/{recording_id}/markdown")
def meeting_markdown(recording_id: int, request: Request):
    """The escape hatch. One meeting, readable anywhere, timestamps intact."""
    require_view(request)
    data = meetings_repo.detail(recording_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No such recording")
    return Response(as_markdown(data), media_type="text/markdown; charset=utf-8")


@app.post("/meetings/{recording_id}/audio")
async def attach_audio(recording_id: int, request: Request,
                       files: list[UploadFile] = File(...)):
    """The recording turned up after the notes did."""
    require_session(request)
    if not files:
        raise HTTPException(status_code=400, detail="No file")
    item = files[0]
    try:
        return upload.attach(recording_id, item.filename, item.file)
    except upload.Rejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await item.close()


@app.get("/meetings/{recording_id}/audio")
def meeting_audio(recording_id: int, request: Request):
    require_view(request)
    data = meetings_repo.detail(recording_id)
    if data is None or not data["recording"]["audio_path"]:
        raise HTTPException(status_code=404, detail="No audio for that recording")
    from .config import BASE_DIR
    return FileResponse(BASE_DIR / data["recording"]["audio_path"],
                        media_type=data["recording"]["mime"] or "audio/mpeg")


@app.post("/meetings/{recording_id}/retry")
def meeting_retry(recording_id: int, request: Request):
    require_session(request)
    with cursor() as conn:
        conn.execute(
            "UPDATE recordings SET status = 'queued', failure = NULL WHERE id = ?",
            (recording_id,),
        )
    return {"ok": True}


@app.post("/meetings/{recording_id}/speaker")
async def meeting_speaker(recording_id: int, request: Request):
    require_session(request)
    body = await request.json()
    meetings_repo.assign_speaker(recording_id, body.get("label", ""), body.get("person"))
    return {"ok": True}


@app.post("/actions/{action_id}/toggle")
def action_toggle(action_id: int, request: Request):
    """Kept for anything still calling it: open becomes done, done becomes open."""
    require_session(request)
    with cursor() as conn:
        row = conn.execute("SELECT state FROM action_items WHERE id = ?",
                           (action_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No such action")
    new = "open" if (row["state"] or "open") == "done" else "done"
    actions_repo.set_state(action_id, new)
    return {"state": new, "done": new == "done"}


@app.post("/actions/{action_id}/state")
async def action_state(action_id: int, request: Request):
    require_session(request)
    body = await request.json()
    try:
        result = actions_repo.set_state(action_id, str(body.get("state", "")),
                                        body.get("note"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result:
        raise HTTPException(status_code=404, detail="No such action")
    return result


# --------------------------------------------------------------------------
# the library
# --------------------------------------------------------------------------
@app.get("/library", response_class=HTMLResponse)
def library_page(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    return page(request, "library.html", "library",
                {"docs": library.listing(), "words": library.total_words()})


@app.get("/library/{document_id}", response_class=HTMLResponse)
def document_page(document_id: int, request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    doc = library.get(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="No such document")
    return page(request, "document.html", "library", {"doc": doc})


@app.post("/library/note")
async def library_note(request: Request):
    require_session(request)
    body = await request.json()
    try:
        return library.add(body.get("title", ""), body.get("body", ""))
    except library.Rejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/library/upload")
async def library_upload(request: Request, files: list[UploadFile] = File(...)):
    require_session(request)
    results = []
    for item in files:
        try:
            raw = await item.read()
            text = library.extract(item.filename, raw)
            added = library.add(Path(item.filename).stem.replace("_", " "), text,
                                kind="file", source_name=Path(item.filename).name,
                                mime=item.content_type, raw=raw)
            results.append({"filename": item.filename, "ok": True, **added})
        except library.Rejected as exc:
            results.append({"filename": item.filename, "ok": False, "reason": str(exc)})
        finally:
            await item.close()
    return {"results": results}


@app.post("/library/{document_id}/forget")
def library_forget(document_id: int, request: Request):
    require_session(request)
    if not library.remove(document_id):
        raise HTTPException(status_code=404, detail="No such document")
    return {"ok": True}


@app.get("/api/library/search")
def library_search(q: str, request: Request):
    require_view(request)
    return library.context_for(q)


# --------------------------------------------------------------------------
# action items, directory, settings
# --------------------------------------------------------------------------
@app.get("/actions", response_class=HTMLResponse)
def actions_page(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    return page(request, "actions.html", "actions", {"data": actions_repo.listing()})


@app.get("/directory", response_class=HTMLResponse)
def directory_page(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    people, unnamed = directory_repo.listing()
    return page(request, "directory.html", "directory",
                {"people": people, "unnamed": unnamed})


@app.post("/directory/{name}")
async def directory_save(name: str, request: Request):
    require_session(request)
    body = await request.json()
    directory_repo.upsert(name, body.get("role"), body.get("org"), body.get("note"))
    return {"ok": True}


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    return page(request, "settings.html", "settings", {
        "devices": passkeys.enrolled_devices(),
        "pipeline": config.PIPELINE,
        "model": config.GEMINI_MODEL,
        "version": config.VERSION,
        "has_pin": secrets_store.has_pin(),
        "pin_min": config.PIN_MIN_DIGITS,
        "pin_max": config.PIN_MAX_DIGITS,
    })


# --------------------------------------------------------------------------
# glossary and chat
# --------------------------------------------------------------------------
@app.get("/api/term")
def term_lookup(q: str, request: Request):
    require_view(request)
    hit = glossary.lookup(q)
    if hit is None:
        return {"known": False, "term": q, "gloss": "", "kind": ""}
    return {"known": True, "term": hit["term"], "gloss": hit["gloss"], "kind": hit["kind"] or ""}


@app.get("/chat", response_class=HTMLResponse)
def chat_index(request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    return page(request, "chat.html", "chat",
                {"threads": chat_repo.threads(), "current": None})


@app.post("/chat/new")
def chat_new(request: Request):
    require_session(request)
    thread_id = chat_repo.start("New conversation")
    return RedirectResponse(f"/chat/{thread_id}", status_code=303)


@app.post("/chat/from-term")
async def chat_from_term(request: Request):
    """The other half of the term popover. Learn more lands in a real thread with
    the question already asked, so the conversation has somewhere to go."""
    require_session(request)
    body = await request.json()
    term = (body.get("term") or "").strip()
    if not term:
        raise HTTPException(status_code=400, detail="No term")
    thread_id = chat_repo.start(term, seed_term=term,
                                recording_id=body.get("recording_id"))
    chat_repo.say(thread_id, f"What is {term}?")
    return {"thread_id": thread_id}


@app.get("/chat/{thread_id}", response_class=HTMLResponse)
def chat_thread(thread_id: int, request: Request):
    if current(request) is None:
        return RedirectResponse("/lock", status_code=302)
    found = chat_repo.thread(thread_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such thread")
    return page(request, "chat.html", "chat",
                {"threads": chat_repo.threads(), "current": found,
                 "files": {f["id"]: f for f in made_repo.for_thread(thread_id)},
                 "made": made_repo.for_thread(thread_id),
                 "formats": [(f, documents.NAMES[f]) for f in documents.FORMATS]})


@app.post("/chat/{thread_id}/say")
async def chat_say(thread_id: int, request: Request):
    require_session(request)
    if chat_repo.thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="No such thread")
    form = await request.form()
    body = str(form.get("body") or "").strip()
    if not body:
        return RedirectResponse(f"/chat/{thread_id}", status_code=303)
    chat_repo.say(thread_id, body)
    return RedirectResponse(f"/chat/{thread_id}", status_code=303)


# --------------------------------------------------------------------------
# documents ENYGMA makes
# --------------------------------------------------------------------------
@app.post("/chat/{thread_id}/document")
async def chat_document(thread_id: int, request: Request):
    """Save as. For when he already has an answer he wants to keep, rather than
    a request he is about to type."""
    require_session(request)
    found = chat_repo.thread(thread_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such thread")
    payload = await request.json()
    fmt = str(payload.get("format") or "").lower()
    if fmt not in documents.FORMATS:
        raise HTTPException(status_code=400,
                            detail=f"Not a format: {fmt or 'none given'}")
    style = "enygma" if payload.get("style") == "enygma" else "plain"

    # Which answer he pressed it on. Without a message the whole thread is the
    # material, which is what "save this conversation" should mean.
    message_id = payload.get("message_id")
    material, brief = [], payload.get("brief") or ""
    for m in found["messages"]:
        material.append(("Operator: " if m["role"] == "operator" else "ENYGMA: ")
                        + m["body"])
        if message_id and m["id"] == message_id:
            # Named for the thread, not for the instruction: "Turn this answer
            # into a document" would otherwise become the document's title.
            brief = brief or f"{found['thread']['title']}"
            material = [m["body"]]
            break
    brief = brief or f"Make a document from this conversation: {found['thread']['title']}"
    try:
        row = made_repo.create(brief, fmt, context="\n\n".join(material),
                               thread_id=thread_id, style=style)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"made": {k: row[k] for k in
                     ("id", "format", "title", "filename", "bytes")}}


@app.get("/files/{made_id}")
def made_file(made_id: int, request: Request):
    """The download. Content-Disposition attachment, because a .md or .html
    served inline opens in the browser instead of saving, and he asked for a
    file."""
    require_view(request)
    found = made_repo.blob(made_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That file is no longer here")
    path, row = found
    return FileResponse(path, media_type=row["mime"], filename=row["filename"],
                        content_disposition_type="attachment")


# --------------------------------------------------------------------------
# the Friday note
# --------------------------------------------------------------------------
@app.post("/week/{week_start}/again")
def week_again(week_start: str, request: Request):
    """Write it again. A deliberate re-roll, so his edit is what he is replacing."""
    require_session(request)
    from datetime import date as _date
    try:
        monday = _date.fromisoformat(week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not a date")
    return {"note": weeknote.write(monday, keep_edit=False)}


@app.post("/week/{week_start}/edit")
async def week_edit(week_start: str, request: Request):
    """His version of the note. Kept beside the generated one, never on top."""
    require_session(request)
    body = await request.json()
    if weeknote.stored_exists(week_start) is False:
        raise HTTPException(status_code=404, detail="No note for that week")
    return {"note": weeknote.save_edit(week_start,
                                       body.get("done") or [],
                                       body.get("next") or [])}


@app.get("/week/{week_start}/text")
def week_text(week_start: str, request: Request):
    """The note as it would land in an email. The clipboard reads this rather
    than scraping the page, so what he pastes is what was stored."""
    require_session(request)
    from datetime import date as _date
    try:
        note = weeknote.stored(_date.fromisoformat(week_start))
    except ValueError:
        raise HTTPException(status_code=400, detail="Not a date")
    if note is None:
        raise HTTPException(status_code=404, detail="No note for that week")
    return {"text": weeknote.as_email(note)}


# --------------------------------------------------------------------------
# error pages
# --------------------------------------------------------------------------
from fastapi.exceptions import HTTPException as _HTTPException  # noqa: E402


@app.exception_handler(_HTTPException)
async def html_errors(request: Request, exc: _HTTPException):
    """A browser asking for a page should get a page, not raw JSON.

    Anything that looks like an API call still gets JSON, because a fetch() that
    receives HTML fails in a way that is much harder to read.
    """
    wants_html = "text/html" in request.headers.get("accept", "")
    if not wants_html:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 401:
        return RedirectResponse("/lock", status_code=302)
    detail = exc.detail if isinstance(exc.detail, str) else "Something is missing."
    return templates.TemplateResponse(
        request, "error.html",
        {"nav": "", "code": exc.status_code, "detail": detail},
        status_code=exc.status_code,
    )
