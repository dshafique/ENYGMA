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
from .ingest import poller, upload
from .pipeline import runner
from .export import as_markdown
from . import (meetings as meetings_repo, actions as actions_repo,
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





# --------------------------------------------------------------------------
# session helpers
# --------------------------------------------------------------------------
def current(request: Request) -> dict | None:
    return session.read(request.cookies.get(session.cookie_name()))


def require_session(request: Request) -> dict:
    """Two different 401s, two different screens.

    reason=locked   -> the lock screen
    reason=stale    -> the compact re-auth sheet, so his place is kept
    """
    state = current(request)
    if state is None:
        raise HTTPException(status_code=401, detail={"reason": "locked"})
    if not state["fresh"]:
        raise HTTPException(status_code=401, detail={"reason": "stale"})
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
        },
    )


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
    require_session(request)
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
    require_session(request)
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
    require_session(request)
    return {"meetings": meetings_repo.listing()}


@app.post("/upload")
async def upload_audio(request: Request, files: list[UploadFile] = File(...)):
    require_session(request)
    results = []
    for item in files:
        try:
            results.append({"filename": item.filename, "ok": True,
                            **upload.store(item.filename, item.file)})
        except upload.Rejected as exc:
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
    require_session(request)
    data = meetings_repo.detail(recording_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No such recording")
    return Response(as_markdown(data), media_type="text/markdown; charset=utf-8")


@app.get("/meetings/{recording_id}/audio")
def meeting_audio(recording_id: int, request: Request):
    require_session(request)
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
    require_session(request)
    with cursor() as conn:
        conn.execute(
            "UPDATE action_items SET done_at = CASE WHEN done_at IS NULL "
            "THEN datetime('now') ELSE NULL END WHERE id = ?", (action_id,))
        row = conn.execute("SELECT done_at FROM action_items WHERE id = ?", (action_id,)).fetchone()
    return {"done": bool(row and row["done_at"])}


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
    })


# --------------------------------------------------------------------------
# glossary and chat
# --------------------------------------------------------------------------
@app.get("/api/term")
def term_lookup(q: str, request: Request):
    require_session(request)
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
                {"threads": chat_repo.threads(), "current": found})


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
