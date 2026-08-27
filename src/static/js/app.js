/* One module for the whole shell. Every block guards on its own elements, so a
   page that does not have a dropzone or a player simply skips that block. */

/* This file was requested as app.js?v=<build>. Anything it imports carries the
   same stamp, so a dynamic import can never pull a cached copy from an older
   build than the one that asked for it: see V, declared with the re-auth
   helpers below. */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/* ---------------------------------------------------------------------------
   Re-authentication.

   Reading needs a session; writing needs a *fresh* one. When the freshness
   window lapses, every write comes back 401 with reason "stale". Without this,
   an upload simply did nothing: the response was parsed as if it were a result
   list, the list was empty, and the interface reported success by saying
   nothing at all. Silence is the worst possible answer to "did that work".

   So: one wrapper around every mutating request. On a stale 401 it raises the
   sheet, waits for a passkey or a PIN, and retries the original request once.
   His place is kept, and the thing he asked for still happens.
--------------------------------------------------------------------------- */
const V = new URL(import.meta.url).search;

function reauth() {
  const scrim = $("#reauth");
  if (!scrim) return Promise.reject(new Error("no re-auth sheet on this page"));
  const msg = $("#reauth-msg");
  const say = (t, bad) => { if (msg) { msg.textContent = t || "";
                                       msg.className = "msg " + (bad ? "danger" : "dim"); } };

  return new Promise((resolve, reject) => {
    const close = (ok, err) => {
      scrim.hidden = true;
      $("#reauth-pinbox").hidden = true;
      $("#reauth-pinval").value = "";
      say("");
      document.removeEventListener("keydown", onKey);
      ok ? resolve() : reject(err || new Error("cancelled"));
    };
    const onKey = (e) => { if (e.key === "Escape") close(false); };

    $("#reauth-go").onclick = async () => {
      try {
        const { unlock } = await import(`/static/js/passkey.js${V}`);
        await unlock(say);
        close(true);
      } catch (e) {
        say(e?.status === 429
          ? `Locked for ${e.data?.detail?.lockout ?? "a few"} seconds`
          : "That did not complete. Try again.", true);
      }
    };
    $("#reauth-pin").onclick = () => { $("#reauth-pinbox").hidden = false; $("#reauth-pinval").focus(); };
    $("#reauth-pingo").onclick = async () => {
      try {
        await post("/auth/pin/verify", { pin: $("#reauth-pinval").value }, { guard: false });
        close(true);
      } catch (e) { say("That PIN did not match", true); }
    };
    $("#reauth-pinval").onkeydown = (e) => { if (e.key === "Enter") $("#reauth-pingo").click(); };
    $("#reauth-cancel").onclick = () => close(false);
    document.addEventListener("keydown", onKey);

    scrim.hidden = false;
    $("#reauth-go").focus();
  });
}

function stale(res, data) {
  return res.status === 401 && (data?.detail?.reason ?? data?.reason) === "stale";
}

async function post(url, body, opts = {}) {
  const send = () => fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let res = await send();
  let data = await res.json().catch(() => ({}));
  if (!res.ok && opts.guard !== false && stale(res, data)) {
    await reauth();
    res = await send();
    data = await res.json().catch(() => ({}));
  }
  if (res.status === 401 && !stale(res, data)) { location.href = "/lock"; return {}; }
  if (!res.ok) throw Object.assign(new Error("request failed"), { status: res.status, data });
  return data;
}

/* Same contract, for requests that are not JSON. */
async function send(url, init) {
  let res = await fetch(url, init);
  if (res.status === 401) {
    const data = await res.clone().json().catch(() => ({}));
    if (stale(res, data)) {
      await reauth();
      res = await fetch(url, init);
    } else {
      location.href = "/lock";
    }
  }
  return res;
}

/* ---------------------------------------------------------------- theme */
{
  const btns = [$("#theme"), $("#theme-m")].filter(Boolean);
  const current = () => {
    const set = document.documentElement.getAttribute("data-theme");
    if (set) return set;
    return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };
  btns.forEach((btn) => btn.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("enygma-theme", next); } catch (e) {}
  }));
}

/* ------------------------------------------------- meetings list filter */
{
  const list = $("#reclist");
  if (list) {
    const search = $("#q");
    const none = $("#nomatch");
    let filter = "all";

    const apply = () => {
      const needle = (search?.value || "").trim().toLowerCase();
      let shown = 0;
      $$(".rec", list).forEach((a) => {
        const okFilter = filter === "all" || a.dataset.status === filter;
        const okText = !needle || a.dataset.title.includes(needle);
        const show = okFilter && okText;
        a.hidden = !show;
        if (show) shown += 1;
      });
      // Hide a day heading whose whole bucket got filtered away.
      $$(".daygroup", list).forEach((g) => {
        g.hidden = $$(".rec", g).every((a) => a.hidden);
      });
      if (none) none.hidden = shown > 0;
    };

    search?.addEventListener("input", apply);
    $$("[data-filter]").forEach((chip) => {
      chip.addEventListener("click", () => {
        $$("[data-filter]").forEach((c) => c.classList.toggle("on", c === chip));
        filter = chip.dataset.filter;
        apply();
      });
    });
  }
}

/* -------------------------------------------------------------- upload */
{
  const drop = $("#drop");
  const input = $("#file");
  const queue = $("#queue");
  if (drop && input) {
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    ["dragenter", "dragover"].forEach((k) =>
      drop.addEventListener(k, (e) => { stop(e); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((k) =>
      drop.addEventListener(k, (e) => { stop(e); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => upload(e.dataTransfer.files));
    input.addEventListener("change", () => upload(input.files));

    async function upload(files) {
      if (!files || !files.length) return;
      const body = new FormData();
      Array.from(files).forEach((f) => body.append("files", f));
      const line = (name, text, bad) =>
        `<div class="q"><span>${name}</span><span class="${bad ? "danger" : "muted"}">${text}</span></div>`;
      queue.innerHTML = Array.from(files).map((f) => line(f.name, "sending")).join("");
      try {
        const res = await send("/upload", { method: "POST", body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          // The failure that started this: a 401 was parsed as an empty result
          // list and the interface said nothing at all.
          queue.innerHTML = Array.from(files)
            .map((f) => line(f.name, `rejected (${res.status})`, true)).join("");
          return;
        }
        const results = data.results || [];
        if (!results.length) {
          queue.innerHTML = line("Upload", "the server accepted nothing", true);
          return;
        }
        queue.innerHTML = results.map((r) => line(
          r.filename,
          r.ok ? (r.duplicate ? "already here" : "queued") : r.reason,
          !r.ok)).join("");
        if (results.some((r) => r.ok)) setTimeout(() => location.reload(), 900);
      } catch (err) {
        queue.innerHTML = line("Upload failed", String(err), true);
      }
    }
  }
}

/* ------------------------------------------------------ detail: tabs */
{
  const tabs = $$("[data-tab]");
  if (tabs.length) {
    tabs.forEach((btn) => btn.addEventListener("click", () => {
      tabs.forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
      $$(".tab").forEach((p) => p.classList.toggle("on", p.id === "tab-" + btn.dataset.tab));
    }));
  }
}

/* ------------------------------------------------- detail: audio + seek */
{
  const audio = $("#audio");
  $$("[data-seek]").forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    const ms = Number(b.dataset.seek);
    if (!audio || Number.isNaN(ms)) return;
    audio.currentTime = ms / 1000;
    audio.play().catch(() => {});
  }));
  if (audio) {
    const segs = $$(".seg");
    audio.addEventListener("timeupdate", () => {
      const ms = audio.currentTime * 1000;
      segs.forEach((s) => {
        const a = Number(s.dataset.start), b = Number(s.dataset.end);
        s.classList.toggle("cur", ms >= a && ms < b);
      });
    });
  }
}

/* ------------------------------------------------------- action items */
$$("[data-action]").forEach((box) => box.addEventListener("change", async () => {
  const row = box.closest(".item");
  try {
    const res = await post(`/actions/${box.dataset.action}/toggle`);
    row?.classList.toggle("done", res.done);
    box.checked = res.done;
  } catch (e) { box.checked = !box.checked; }
}));

/* ------------------------------------------------------ speaker naming */
$$("[data-speaker]").forEach((input) => {
  const save = async () => {
    try {
      await post(`/meetings/${input.dataset.rec}/speaker`, {
        label: input.dataset.speaker, person: input.value,
      });
      const chip = input.closest(".spk");
      chip?.classList.toggle("unnamed", !input.value.trim());
      const av = chip?.querySelector(".av");
      if (av) {
        const n = input.value.trim() || input.dataset.speaker;
        const parts = n.split(/\s+/).filter(Boolean);
        av.textContent = (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0]
                                           : n.slice(0, 2)).toUpperCase();
      }
    } catch (e) {}
  };
  input.addEventListener("change", save);
  input.addEventListener("blur", save);
});

/* ------------------------------------------------------------- retry */
$("#retry")?.addEventListener("click", async (e) => {
  await post(`/meetings/${e.target.dataset.id}/retry`);
  location.reload();
});

/* --------------------------------------------- refresh while running */
{
  /* Scope matters. A transcribing pill in the list pane is not a reason to
     reload the meeting someone is reading: it throws away their scroll position,
     their open tab and any popover. Only refresh for what is actually on view. */
  const detail = $("#detail");
  const openMeeting = detail && detail.querySelector(".detail-inner h1");
  const watched = openMeeting ? detail : document;
  const running = watched.querySelectorAll(".pill.transcribing, .pill.queued").length > 0;

  const busy = () => !$("#pop")?.hidden ||
                     ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);

  if (running) {
    const tick = () => { if (busy()) setTimeout(tick, 4000); else location.reload(); };
    setTimeout(tick, 8000);
  }
}

/* ------------------------------------------------------ term popover */
{
  const pop = $("#pop");
  const scope = $(".termable");
  if (pop && scope) {
    let wrap = null, timer = null, term = "", justOpened = false;

    const place = (x, y) => {
      pop.hidden = false;
      const w = pop.offsetWidth, h = pop.offsetHeight;
      const left = Math.min(Math.max(8, x - w / 2), window.innerWidth - w - 8);
      const top = y + h + 24 > window.innerHeight ? y - h - 14 : y + 14;
      pop.style.left = `${left + window.scrollX}px`;
      pop.style.top = `${top + window.scrollY}px`;
    };

    const unwrap = () => {
      if (!wrap) return;
      const parent = wrap.parentNode;
      while (wrap.firstChild) parent.insertBefore(wrap.firstChild, wrap);
      parent.removeChild(wrap);
      parent.normalize();
      wrap = null;
    };

    const clear = () => { unwrap(); pop.hidden = true; };

    /* The range for the whole word under the point, not the caret offset. */
    const wordRange = (x, y) => {
      const at = document.caretRangeFromPoint
        ? document.caretRangeFromPoint(x, y) : null;
      if (!at || at.startContainer.nodeType !== 3) return null;
      const text = at.startContainer.textContent;
      let a = at.startOffset, b = at.startOffset;
      const isWord = (c) => c && /[\w'\-]/.test(c);
      while (isWord(text[a - 1])) a -= 1;
      while (isWord(text[b])) b += 1;
      if (b - a < 2) return null;
      const range = document.createRange();
      range.setStart(at.startContainer, a);
      range.setEnd(at.startContainer, b);
      return range;
    };

    async function open(range, x, y) {
      term = range.toString().replace(/^[-']+|[-']+$/g, "");
      if (term.length < 2) return;
      unwrap();
      wrap = document.createElement("span");
      wrap.className = "term-hit";
      try { range.surroundContents(wrap); } catch (e) { wrap = null; }

      $("#pop-term").textContent = term;
      $("#pop-kind").textContent = "";
      $("#pop-gloss").textContent = "Looking\u2026";
      justOpened = true;
      place(x, y);
      try {
        const res = await fetch(`/api/term?q=${encodeURIComponent(term)}`);
        const data = await res.json();
        $("#pop-kind").textContent = data.kind || (data.known ? "" : "not in the glossary yet");
        $("#pop-gloss").textContent = data.gloss ||
          "ENYGMA has no definition for this one. Learn more opens it in Chat.";
      } catch (e) {
        $("#pop-gloss").textContent = "Could not look that up.";
      }
      place(x, y);
    }

    let downAt = null;
    scope.addEventListener("pointerdown", (e) => {
      downAt = { x: e.clientX, y: e.clientY };
      timer = setTimeout(() => {
        const range = wordRange(downAt.x, downAt.y);
        if (range) open(range, downAt.x, downAt.y);
      }, 420);
    });
    const cancel = () => clearTimeout(timer);
    scope.addEventListener("pointerup", cancel);
    scope.addEventListener("pointercancel", cancel);
    scope.addEventListener("pointermove", (e) => {
      if (downAt && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 8) cancel();
    });
    // A long press on a touch screen fires the context menu; suppress it only
    // when the popover is what the press produced.
    scope.addEventListener("contextmenu", (e) => { if (!pop.hidden) e.preventDefault(); });

    $("#pop-close")?.addEventListener("click", clear);
    // The click that ends the long press must not be the click that closes it.
    document.addEventListener("click", (e) => {
      if (justOpened) { justOpened = false; return; }
      if (!pop.hidden && !pop.contains(e.target)) clear();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") clear(); });

    $("#pop-more")?.addEventListener("click", async () => {
      const id = Number(location.pathname.split("/").pop());
      const res = await post("/chat/from-term", {
        term, recording_id: Number.isNaN(id) ? null : id,
      });
      location.href = `/chat/${res.thread_id}`;
    });
  }
}

/* ------------------------------------------------------- copy as markdown */
{
  const button = $("#copymd");
  const note = $("#copymsg");
  button?.addEventListener("click", async () => {
    const say = (t) => { if (note) { note.textContent = t;
                         setTimeout(() => (note.textContent = ""), 2600); } };
    try {
      const res = await send(`/meetings/${button.dataset.id}/markdown`);
      if (!res.ok) throw new Error(res.status);
      const text = await res.text();
      // navigator.clipboard needs a secure context. Over plain http on a LAN
      // there is not one, so fall back rather than failing silently.
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        say("Copied");
      } else {
        const box = document.createElement("textarea");
        box.value = text;
        box.style.cssText = "position:fixed;top:-1000px";
        document.body.appendChild(box);
        box.select();
        const ok = document.execCommand("copy");
        box.remove();
        say(ok ? "Copied" : "Could not copy \u2014 open /markdown and select all");
      }
    } catch (e) {
      say("Could not copy");
    }
  });
}

/* -------------------------------------------------------------- chat */
{
  const convo = $("#convo");
  if (convo) convo.scrollTop = convo.scrollHeight;
  const body = $("#body");
  const form = $("#say");
  body?.addEventListener("input", () => {
    body.style.height = "auto";
    body.style.height = Math.min(body.scrollHeight, 180) + "px";
  });
  body?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form?.requestSubmit(); }
  });
  // Submitted through fetch rather than as a form post, so a stale session
  // raises the sheet instead of bouncing him to the lock screen and throwing
  // away what he had typed.
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = body.value.trim();
    if (!text) return;
    const data = new FormData();
    data.append("body", text);
    const res = await send(form.action, { method: "POST", body: data });
    if (res.ok) location.reload();
  });
}

/* ----------------------------------------------------------- settings */
{
  $("#lock")?.addEventListener("click", async () => {
    await post("/auth/logout"); location.href = "/lock";
  });
  $$("[data-revoke]").forEach((b) => b.addEventListener("click", async () => {
    await post(`/auth/devices/${b.dataset.revoke}/revoke`); location.reload();
  }));
  const pinmsg = $("#pinmsg");
  const pinSay = (t) => { if (pinmsg) { pinmsg.textContent = t;
                          setTimeout(() => (pinmsg.textContent = ""), 3200); } };
  $("#setpin")?.addEventListener("click", async () => {
    try {
      await post("/auth/pin/set", { pin: $("#newpin").value });
      $("#newpin").value = "";
      pinSay("Saved");
      setTimeout(() => location.reload(), 700);
    } catch (e) { pinSay(e.data?.detail || "That PIN was not accepted"); }
  });
  $("#clearpin")?.addEventListener("click", async () => {
    await post("/auth/pin/clear"); location.reload();
  });

  $("#pairnew")?.addEventListener("click", async () => {
    try {
      const res = await post("/auth/pairing/new", {});
      $("#paircode").textContent = res.code;
      $("#pairmins").textContent = res.minutes;
      $("#pairout").hidden = false;
    } catch (e) { /* the sheet handled it, or it genuinely failed */ }
  });

  const add = $("#addkey");
  if (add) add.addEventListener("click", async () => {
    const { enrol } = await import(`/static/js/passkey.js${V}`);
    try { await enrol(navigator.userAgent.includes("Android") ? "Android device" : "This device",
                      () => {}); location.reload(); }
    catch (e) { add.textContent = "That did not complete"; }
  });
}
