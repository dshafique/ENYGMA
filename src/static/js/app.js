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
// Set by the upload block, used by the recorder: a recording goes up the same
// way a dropped file does, lands in the same queue, and shows the same words
// back. Two upload paths would be two sets of failure messages.
let sendFiles = null;

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

    sendFiles = upload;

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

/* ------------------------------------------------- the Friday reminder */
/* The note is written for him whether or not he looks at it, which is the
   problem: a note nobody opens is a note nobody sends. So on Friday the phone
   taps him on the shoulder.

   Scheduled on the device, not pushed from the Spark. A push would need
   Firebase, a token table and a sender in the worker, and would put a Google
   dependency in the middle of something that is otherwise entirely his. A
   repeating local alarm needs none of that, and "it is Friday afternoon" is a
   fact the phone already knows.

   Only inside the native shell. A browser tab cannot hold an alarm, and asking
   for notification permission in one would be a prompt that buys nothing.

   Rescheduled on every launch with the same id, which replaces rather than
   stacks -- so changing ENYGMA_WEEKNOTE_HOUR moves the reminder the next time
   he opens the app, and a hundred launches do not make a hundred alarms. */
{
  const cap = window.Capacitor;
  const Notify = cap && cap.isNativePlatform && cap.isNativePlatform()
    ? (cap.Plugins || {}).LocalNotifications : null;

  if (Notify) {
    const meta = document.querySelector('meta[name="enygma-weeknote-hour"]');
    const written = parseInt(meta && meta.content, 10);
    // An hour after the note is written, so the worker has finished before the
    // phone claims it is ready. Landing first would send him to an empty card.
    const hour = (Number.isFinite(written) ? written : 15) + 1;

    (async () => {
      try {
        let allowed = await Notify.checkPermissions();
        if (allowed && allowed.display !== "granted") {
          allowed = await Notify.requestPermissions();
        }
        if (!allowed || allowed.display !== "granted") return;
        await Notify.schedule({
          notifications: [{
            id: 4073,
            title: "Your week is written",
            body: "Read it before you send it.",
            // Capacitor counts weekdays from Sunday, so Friday is 6.
            schedule: { on: { weekday: 6, hour: Math.min(hour, 23), minute: 0 },
                        allowWhileIdle: true },
          }],
        });
      } catch (e) {
        // A phone that refuses the alarm still has a working app.
      }
    })();
  }
}

/* ----------------------------------------------------------- recording */
/* Press record, walk into the meeting, press stop. That is the whole feature,
   and it is the one that changes how ENYGMA gets used: before this, catching a
   meeting meant opening the phone's voice recorder, remembering to stop it,
   coming back here and finding the file in a picker -- three apps and a manual
   step at the exact moment he is least able to fiddle.

   Two engines behind one button. In a browser it is MediaRecorder, which works
   and is at the mercy of the tab staying alive. Inside the native shell it is
   the Capacitor plugin with a foreground service, which survives the screen
   going off and the phone going in a pocket. The page picks at runtime and the
   rest of the code below cannot tell which it got. */
{
  const box = $("#recorder");
  const button = $("#rec");
  const clock = $("#rectime");
  const hold = $("#recpause");
  const drop = $("#reccancel");
  const msg = $("#recmsg");
  const say = (t, bad) => {
    if (!msg) return;
    msg.textContent = t || "";
    msg.classList.toggle("danger", !!bad);
  };

  const cap = window.Capacitor;
  const isNative = !!(cap && cap.isNativePlatform && cap.isNativePlatform());
  const plugins = (cap && cap.Plugins) || {};

  const two = (n) => String(n).padStart(2, "0");
  const spell = (ms) => {
    const all = Math.floor(ms / 1000);
    const h = Math.floor(all / 3600);
    const m = Math.floor((all % 3600) / 60);
    return (h ? `${h}:${two(m)}` : `${m}`) + ":" + two(all % 60);
  };

  /* A name he will recognise in a list a week later. Deliberately not
     2026-09-04T173000: the ingest strips a leading timestamp from a title,
     which would leave every recording called "Untitled recording". */
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const named = (ext) => {
    const now = new Date();
    return `Recording ${now.getDate()} ${MONTHS[now.getMonth()]} ` +
           `${two(now.getHours())}.${two(now.getMinutes())}.${ext}`;
  };

  /* ---- the browser engine */
  function inBrowser() {
    let media = null, chunks = [], stream = null, type = "";
    /* Opus in WebM is what Chrome and Android give and they offer no say in it.
       The server remuxes to Ogg on the way in, losslessly, because the
       transcription model reads Ogg and does not read WebM. */
    const WANTED = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
    return {
      supported: !!(navigator.mediaDevices && window.MediaRecorder),
      async start() {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
        });
        type = WANTED.find((t) => MediaRecorder.isTypeSupported(t)) || "";
        media = new MediaRecorder(stream, type ? { mimeType: type, audioBitsPerSecond: 48000 } : {});
        chunks = [];
        media.addEventListener("dataavailable", (e) => { if (e.data.size) chunks.push(e.data); });
        // A slice a second, so a crash costs a second rather than the meeting.
        media.start(1000);
      },
      pause() { media && media.state === "recording" && media.pause(); },
      resume() { media && media.state === "paused" && media.resume(); },
      async stop() {
        const done = new Promise((yes) => media.addEventListener("stop", yes, { once: true }));
        media.stop();
        await done;
        stream.getTracks().forEach((t) => t.stop());
        const mime = media.mimeType || type || "audio/webm";
        const ext = mime.includes("ogg") ? "ogg" : mime.includes("mp4") ? "m4a" : "webm";
        return new File(chunks, named(ext), { type: mime.split(";")[0] });
      },
      async cancel() {
        try { media && media.state !== "inactive" && media.stop(); } catch (e) {}
        stream && stream.getTracks().forEach((t) => t.stop());
        chunks = [];
      },
    };
  }

  /* ---- the native engine
     The recorder plugin writes a file and hands back its path. That path cannot
     be fetched from this page: the app loads from enygma.arkhm.io and the
     native file handler answers on another origin, so a fetch at it is
     cross-origin and blocked. Filesystem.readFile brings the bytes across
     instead. */
  function inShell() {
    const Rec = plugins.AudioRecorder;
    const Files = plugins.Filesystem;
    const Service = plugins.ForegroundService;
    return {
      supported: !!(Rec && Files),
      async start() {
        const ok = await Rec.requestPermissions();
        if (ok && ok.microphone && ok.microphone !== "granted") {
          throw new Error("The microphone is not allowed. Turn it on in Android settings.");
        }
        await Rec.startRecording();
        // The notification is what stops Android killing the process. Without
        // it the recording ends when the screen does, silently.
        if (Service) {
          try {
            await Service.startForegroundService({
              id: 4073, title: "ENYGMA", body: "Recording this meeting",
              smallIcon: "ic_stat_icon",
            });
          } catch (e) { /* recording still works in the foreground */ }
        }
      },
      pause() { Rec.pauseRecording && Rec.pauseRecording(); },
      resume() { Rec.resumeRecording && Rec.resumeRecording(); },
      async stop() {
        const out = await Rec.stopRecording();
        if (Service) { try { await Service.stopForegroundService(); } catch (e) {} }
        const read = await Files.readFile({ path: out.uri });
        const raw = atob(read.data);
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        const ext = (out.uri.split(".").pop() || "m4a").toLowerCase();
        const mime = ext === "m4a" ? "audio/mp4" : ext === "aac" ? "audio/aac" : "audio/ogg";
        return new File([bytes], named(ext), { type: mime });
      },
      async cancel() {
        try { await Rec.cancelRecording(); } catch (e) {}
        if (Service) { try { await Service.stopForegroundService(); } catch (e) {} }
      },
    };
  }

  const engine = isNative ? inShell() : inBrowser();

  if (box && !engine.supported) {
    box.hidden = true;                 // no microphone here; the dropzone remains
  }

  /* began: when it started. held: how long it has been paused for in total.
     heldAt: when the current pause began, or 0. The clock reads the same while
     paused as it did the moment it was paused. */
  let going = false, ticker = null, began = 0, held = 0, heldAt = 0;
  const paused = () => heldAt !== 0;
  const elapsed = () => (heldAt || Date.now()) - began - held;

  const show = () => { if (clock) clock.textContent = spell(going ? elapsed() : 0); };
  const dressed = () => {
    box && box.classList.toggle("on", going);
    box && box.classList.toggle("held", paused());
    // The word only. Writing to the button itself would take the recording dot
    // with it, and it never came back.
    const word = button && button.querySelector(".recword");
    if (word) word.textContent = going ? "Stop" : "Record";
    [clock, hold, drop].forEach((el) => { if (el) el.hidden = !going; });
    if (hold) hold.textContent = paused() ? "Resume" : "Pause";
  };

  // Leaving the page ends the recording, so say so rather than losing it. In
  // the native shell this never fires, which is the point of the native shell.
  const guard = (e) => { e.preventDefault(); e.returnValue = ""; };

  button?.addEventListener("click", async () => {
    if (!going) {
      button.disabled = true;
      say("");
      try {
        await engine.start();
      } catch (err) {
        say(err && err.name === "NotAllowedError"
            ? "The microphone was refused. Allow it for this site and try again."
            : `Could not start recording: ${err && err.message ? err.message : err}`, true);
        button.disabled = false;
        return;
      }
      going = true; began = Date.now(); held = 0; heldAt = 0;
      button.disabled = false;
      window.addEventListener("beforeunload", guard);
      ticker = setInterval(show, 500);
      show(); dressed();
      return;
    }

    // Stopping. The file goes up the same path a dropped one does.
    button.disabled = true;
    clearInterval(ticker);
    try {
      const spent = elapsed();
      const file = await engine.stop();
      going = false; heldAt = 0;
      window.removeEventListener("beforeunload", guard);
      dressed();
      if (!file.size) { say("That recording came out empty. Nothing was sent.", true); return; }
      say(`Sending ${spell(spent)} of audio\u2026`);
      if (sendFiles) await sendFiles([file]);
      else say("Recorded, but the uploader is not on this page.", true);
    } catch (err) {
      say(`Could not save that recording: ${err && err.message ? err.message : err}`, true);
      going = false;
      window.removeEventListener("beforeunload", guard);
      dressed();
    } finally {
      button.disabled = false;
    }
  });

  hold?.addEventListener("click", () => {
    if (!going) return;
    if (paused()) {
      held += Date.now() - heldAt;
      heldAt = 0;
      engine.resume();
    } else {
      heldAt = Date.now();
      engine.pause();
    }
    dressed(); show();
  });

  drop?.addEventListener("click", async () => {
    if (!going) return;
    if (!confirm("Throw this recording away? It has not been saved anywhere.")) return;
    clearInterval(ticker);
    await engine.cancel();
    going = false; heldAt = 0;
    window.removeEventListener("beforeunload", guard);
    dressed();
    say("Discarded.");
  });
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

/* --------------------------------- the recording arrived after the notes */
{
  const zone = $("#attach");
  const input = $("#attachfile");
  const queue = $("#attachqueue");
  if (zone && input && queue) {
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    ["dragenter", "dragover"].forEach((k) =>
      zone.addEventListener(k, (e) => { stop(e); zone.classList.add("over"); }));
    ["dragleave", "drop"].forEach((k) =>
      zone.addEventListener(k, (e) => { stop(e); zone.classList.remove("over"); }));
    zone.addEventListener("drop", (e) => attach(e.dataTransfer.files));
    input.addEventListener("change", () => attach(input.files));

    async function attach(files) {
      if (!files || !files.length) return;
      const body = new FormData();
      body.append("files", files[0]);
      const line = (t, bad) =>
        `<div class="q"><span>${files[0].name}</span><span class="${bad ? "danger" : "muted"}">${t}</span></div>`;
      queue.innerHTML = line("sending");
      try {
        const res = await send(`/meetings/${queue.dataset.id}/audio`,
                               { method: "POST", body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { queue.innerHTML = line(data.detail || `rejected (${res.status})`, true); return; }
        queue.innerHTML = line("queued, transcribing now");
        setTimeout(() => location.reload(), 1200);
      } catch (err) { queue.innerHTML = line(String(err), true); }
    }
  }
}

/* ------------------------------------------------------- action items */
/* Four states, not a checkbox. Declining something and not having got to it are
   different answers, and the list is only worth reading if it can tell them
   apart. The row restyles itself immediately and reverts if the write fails. */
$$("select.statepick").forEach((pick) => {
  let previous = pick.dataset.state;
  pick.addEventListener("change", async () => {
    const row = pick.closest(".item");
    const chosen = pick.value;
    const paint = (state) => {
      pick.dataset.state = state;
      pick.closest(".statewrap")?.setAttribute("data-state", state);
      if (row) row.className = row.className.replace(/state-\w+/, `state-${state}`);
    };
    paint(chosen);
    try {
      await post(`/actions/${pick.dataset.action}/state`, { state: chosen });
      previous = chosen;
    } catch (e) {
      pick.value = previous;
      paint(previous);
    }
  });
});

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

/* ----------------------------------------------------------- library */
{
  const drop = $("#libdrop");
  const input = $("#libfile");
  const queue = $("#libqueue");
  if (drop && input) {
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    ["dragenter", "dragover"].forEach((k) =>
      drop.addEventListener(k, (e) => { stop(e); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((k) =>
      drop.addEventListener(k, (e) => { stop(e); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => take(e.dataTransfer.files));
    input.addEventListener("change", () => take(input.files));

    async function take(files) {
      if (!files || !files.length) return;
      const body = new FormData();
      Array.from(files).forEach((f) => body.append("files", f));
      const line = (n, t, bad) =>
        `<div class="q"><span>${n}</span><span class="${bad ? "danger" : "muted"}">${t}</span></div>`;
      queue.innerHTML = Array.from(files).map((f) => line(f.name, "reading")).join("");
      try {
        const res = await send("/library/upload", { method: "POST", body });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          queue.innerHTML = line("Upload", `rejected (${res.status})`, true);
          return;
        }
        const results = data.results || [];
        queue.innerHTML = results.map((r) => line(
          r.filename,
          r.ok ? (r.duplicate ? "already in the library" : `added, ${r.chunks} passages`)
               : r.reason,
          !r.ok)).join("");
        if (results.some((r) => r.ok)) setTimeout(() => location.reload(), 1100);
      } catch (err) {
        queue.innerHTML = line("Upload failed", String(err), true);
      }
    }
  }

  const noteForm = $("#notefm");
  noteForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("#notemsg");
    try {
      const res = await post("/library/note", {
        title: $("#notetitle").value, body: $("#notebody").value,
      });
      if (msg) msg.textContent = res.duplicate ? "Already in the library" : "Added";
      if (!res.duplicate) setTimeout(() => location.reload(), 600);
    } catch (err) {
      if (msg) msg.textContent = err.data?.detail || "That was not accepted";
    }
  });

  $$("[data-forget]").forEach((b) => b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      await post(`/library/${b.dataset.forget}/forget`);
      location.href = "/library";
    } catch (e) { b.disabled = false; }
  }));
}

/* -------------------------------------------------------------- chat */
{
  const convo = $("#convo");
  /* On a phone the transcript is not its own scroller -- the page is -- so
     scrolling the element does nothing and the newest answer stays off screen.
     Scroll whichever one actually moves. */
  const toBottom = () => {
    if (!convo) return;
    if (convo.scrollHeight > convo.clientHeight + 1) {
      convo.scrollTop = convo.scrollHeight;
    } else {
      window.scrollTo(0, document.documentElement.scrollHeight);
    }
  };
  toBottom();
  const body = $("#body");
  const form = $("#say");
  // The form still posts to /say without JavaScript, so the thread id comes off
  // its action rather than from a second attribute that could disagree with it.
  const threadId = (form?.getAttribute("action") || "").split("/")[2];

  const grow = () => {
    if (!body) return;
    body.style.height = "auto";
    body.style.height = Math.min(body.scrollHeight, 180) + "px";
  };
  body?.addEventListener("input", grow);

  /* Typing hides the tab bar. Six tabs are 60px, and with a keyboard open on a
     folding phone's cover screen there is not much more than a hundred to
     spend.

     Both halves below exist because of one bug. Hiding the bar on focus and
     restoring it on blur meant that pressing Send blurred the box, which put
     the bar back, which moved the composer up sixty pixels -- between his
     finger going down and coming up. The button slid out from under his thumb
     at the exact moment he pressed it, and nothing happened at all.

     So: pressing Send does not take focus off the box, and the bar comes back
     only once focus has genuinely left the composer, not while it is moving
     around inside it. */
  const typing = (on) => document.documentElement.classList.toggle("typing", on);
  const composer = form?.closest(".composer");

  const sendBtn = $("#send");
  sendBtn?.addEventListener("pointerdown", (e) => e.preventDefault());
  sendBtn?.addEventListener("mousedown", (e) => e.preventDefault());

  let leaving = null;
  composer?.addEventListener("focusin", () => {
    clearTimeout(leaving);
    typing(true);
    setTimeout(toBottom, 250);
  });
  composer?.addEventListener("focusout", () => {
    // A tick, so focus moving from the box to the button is not a departure.
    leaving = setTimeout(() => {
      if (!composer.contains(document.activeElement)) typing(false);
    }, 120);
  });

  /* Enter sends only where there is a Shift key to hold for a newline.
     On a phone the return key is the ONLY way to start a new line, and there is
     no Shift+Enter to fall back on, so sending on Enter meant a half-finished
     sentence was posted the moment he reached for a line break -- four times,
     in the case that turned this up. Touch keyboards get a return key that
     returns; the send button is how a message is sent. */
  const keyboardSends = matchMedia("(hover: hover) and (pointer: fine)").matches;
  body?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
    if (!keyboardSends || e.shiftKey) return;
    e.preventDefault();
    form?.requestSubmit();
  });

  /* One turn at a time, and the button that sends is the button that stops.

     Two controls would be one more thing to hit on a folding phone, and every
     chat he has used puts Stop exactly where Send was. So the button changes
     face while an answer is being written and changes back when it is done. */
  let sending = false;

  const asStop = (on) => {
    if (!sendBtn) return;
    sendBtn.classList.toggle("stopping", on);
    sendBtn.setAttribute("aria-label", on ? "Stop" : "Send");
    sendBtn.disabled = false;
  };

  const pending = (text) => {
    if (!convo) return null;
    const empty = convo.querySelector(".empty");
    if (empty) empty.remove();
    const wrap = document.createElement("div");
    wrap.innerHTML =
      '<div class="turn operator"><div class="who"><span class="label">You</span></div>' +
      '<div class="bubble"></div></div>' +
      '<div class="turn enygma pending"><div class="who"><span class="label">ENYGMA</span></div>' +
      '<div class="bubble dim">Thinking\u2026</div></div>';
    wrap.querySelector(".turn.operator .bubble").textContent = text;
    const nodes = Array.from(wrap.children);
    nodes.forEach((n) => convo.appendChild(n));
    toBottom();
    return nodes;
  };

  form?.addEventListener("submit", async (e) => {
    e.preventDefault();

    /* Second press: stop. The server is told, rather than the connection being
       dropped, so the server keeps what it generated and writes it down. It
       decides what was said; this page never tells it. */
    if (sending) {
      asStop(false);
      sendBtn && (sendBtn.disabled = true);
      try { await post(`/chat/${threadId}/stop`, {}); } catch (err) { /* it ends anyway */ }
      return;
    }

    const text = body.value.trim();
    if (!text) return;

    sending = true;
    // Cleared straight away: whatever else happens, the same sentence cannot be
    // sent twice by a second press landing on text that was never taken away.
    body.value = "";
    grow();
    const shown = pending(text);
    const bubble = shown?.[1]?.querySelector(".bubble");
    asStop(true);

    const restore = () => {
      shown?.forEach((n) => n.remove());
      body.value = text;
      grow();
      body.focus();
    };

    /* Deltas land in the bubble as they arrive. Written as textContent, never
       innerHTML: what comes back is model output, and it goes on screen the
       same way a stored turn does. */
    let got = "";
    let started = false;
    const put = (piece) => {
      if (!bubble) return;
      if (!started) {
        bubble.textContent = "";
        bubble.classList.remove("dim");
        shown?.[1]?.classList.remove("pending");
        shown?.[1]?.classList.add("writing");
        started = true;
      }
      got += piece;
      bubble.textContent = got;
      toBottom();
    };

    try {
      const data = new FormData();
      data.append("body", text);
      const res = await send(`/chat/${threadId}/stream`, { method: "POST", body: data });
      if (!res.ok || !res.body) { restore(); return; }

      const reader = res.body.getReader();
      const decode = new TextDecoder();
      let buffer = "";
      let ended = false;

      while (!ended) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decode.decode(value, { stream: true });
        // SSE separates events with a blank line. A partial one stays in the
        // buffer until the rest of it turns up.
        let cut;
        while ((cut = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, cut);
          buffer = buffer.slice(cut + 2);
          if (!chunk.startsWith("data:")) continue;
          let event;
          try { event = JSON.parse(chunk.slice(5).trim()); } catch (err) { continue; }
          if (event.delta) put(event.delta);
          if (event.replace) { got = ""; started = false; put(event.replace); }
          if (event.done) { ended = true; break; }
        }
      }
      // The turn is stored, and a reload is what renders it properly: the Save
      // as control, any file it built, the mark on a stopped answer.
      location.reload();
    } catch (err) {
      if (!got) restore();
      else location.reload();
    } finally {
      sending = false;
      asStop(false);
    }
  });
}

/* ------------------------------------------------------------- the keyboard */
{
  /* Measure the keyboard instead of trusting the browser to move things.
     interactive-widget=resizes-content is a Chrome feature. Samsung Internet,
     which is the default browser on the phone this runs on, does not honour it:
     the layout viewport never shrinks, so anything stuck to the bottom of it is
     stuck behind the keyboard, and he is typing into a box he cannot see.

     visualViewport is the thing that always knows. The difference between it
     and the window is the keyboard, whatever the browser has decided to do
     about the layout, so everything that needs to sit above the keyboard is
     offset by that one number. */
  const vv = window.visualViewport;
  if (vv) {
    const root = document.documentElement;
    const measure = () => {
      // How much of the window the keyboard is covering.
      const covered = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      // Under about 80px it is a browser chrome change, not a keyboard, and
      // moving the writing bar for a toolbar sliding away looks like a fault.
      root.style.setProperty("--kb", covered > 80 ? `${Math.round(covered)}px` : "0px");
    };
    vv.addEventListener("resize", measure);
    vv.addEventListener("scroll", measure);
    measure();

    /* And keep the caret in sight. A textarea that has grown past the screen
       will happily let him type below the fold, and the browser only scrolls
       the caret into view when it thinks the viewport changed. */
    const inSight = (el) => {
      if (!el) return;
      const r = el.getBoundingClientRect();
      const floor = vv.height - 24;
      if (r.bottom > floor) window.scrollBy({ top: r.bottom - floor, behavior: "smooth" });
    };
    document.addEventListener("focusin", (e) => {
      if (e.target.matches("textarea, input")) setTimeout(() => inSight(e.target), 300);
    });
  }
}

/* -------------------------------------------------------------- the opening */
{
  /* A tap ends it. It is under a second, but a second is a long time to a
     person who opened the app to write one line down before they forget it,
     and an animation nobody can get past is an animation they come to resent. */
  const splash = $("#splash");
  if (splash) {
    const skip = () => splash.remove();
    splash.addEventListener("pointerdown", skip);
    // Whatever happens, it is not still there afterwards.
    setTimeout(skip, 1750);
  }
}

/* ------------------------------------------------------------- what changed */
{
  /* Once per device per release, and only for a device that has been here
     before. A device seeing ENYGMA for the first time is shown nothing and
     quietly marked current: a wall of history is not a welcome.

     The decision is made here rather than on the server because the answer
     depends on what this particular phone has already seen, and asking the
     server that would be a round trip on every open. */
  const scrim = $("#newsheet");
  const holder = $("#releases");
  const raw = $("#changelog");
  if (scrim && holder && raw) {
    const latest = scrim.dataset.latest;
    let seen = null;
    try { seen = localStorage.getItem("enygma-seen"); } catch (e) { seen = latest; }

    const remember = () => { try { localStorage.setItem("enygma-seen", latest); }
                             catch (e) {} };

    if (seen !== latest) {
      let releases = [];
      try { releases = JSON.parse(raw.textContent) || []; } catch (e) {}
      const marks = releases.map((r) => r.mark);
      const at = marks.indexOf(seen);
      // Unknown or absent: nothing useful to catch them up on.
      const show = at > 0 ? releases.slice(0, at) : [];

      if (show.length) {
        for (const release of show) {
          const el = document.createElement("div");
          el.className = "release";
          const mark = document.createElement("div");
          mark.className = "rmark";
          mark.textContent = `${release.mark} · ${release.date}`;
          const head = document.createElement("h3");
          head.textContent = release.headline;
          const list = document.createElement("ul");
          for (const item of release.items || []) {
            const li = document.createElement("li");
            li.textContent = item;
            list.append(li);
          }
          el.append(mark, head, list);
          holder.append(el);
        }
        // After the opening has finished, not on top of it.
        setTimeout(() => { scrim.hidden = false; }, 1150);
      } else {
        remember();
      }
    }

    const close = () => { scrim.hidden = true; remember(); };
    $("#newsheet-close")?.addEventListener("click", close);
    scrim.addEventListener("click", (e) => { if (e.target === scrim) close(); });
  }
}

/* ------------------------------------------------------------------ the bench */
{
  /* Crossing something off asks why, once, in a sheet. Two states only work if
     the reason survives, and a checkbox cannot carry one. Putting an entry back
     never asks: reopening is not a decision anybody needs explained. */
  const sheet = $("#whysheet");
  const field = $("#whyfield");
  let pending = null;

  const openWhy = (on) => { if (sheet) sheet.hidden = !on; };

  const send = async (id, done, note) => {
    try {
      await post(`/backlog/${id}/state`, { done, note: note || null });
      location.reload();
    } catch (e) {
      location.reload();          // whatever happened, the list is the truth
    }
  };

  $$("[data-cross]").forEach((box) => {
    box.addEventListener("change", () => {
      const id = Number(box.dataset.cross);
      if (!box.checked) return send(id, false, null);
      pending = id;
      if (field) field.value = "";
      openWhy(true);
      field?.focus();
    });
  });

  $("#whysave")?.addEventListener("click", () => {
    openWhy(false); send(pending, true, field?.value.trim());
  });
  $("#whyskip")?.addEventListener("click", () => {
    openWhy(false); send(pending, true, null);
  });
  field?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("#whysave")?.click(); }
  });
  sheet?.addEventListener("click", (e) => {
    if (e.target === sheet) { openWhy(false); location.reload(); }
  });

  /* A note saves itself. He is writing at a bench, on a phone, and a Save
     button he has to remember is a note he loses. */
  const body = $("#notebody");
  const state = $("#notestate");
  if (body) {
    const grow = () => { body.style.height = "auto";
                         body.style.height = Math.max(body.scrollHeight, 400) + "px"; };
    grow();
    let timer = null, last = body.value;
    const save = async () => {
      if (body.value === last) return;
      last = body.value;
      if (state) state.textContent = "Saving";
      try {
        const res = await post(`/notes/${body.dataset.note}`, { body: body.value });
        if (state) state.textContent = "Saved";
      } catch (e) {
        if (state) state.textContent = "Not saved. Your words are still here.";
      }
    };
    body.addEventListener("input", () => {
      grow();
      clearTimeout(timer);
      timer = setTimeout(save, 900);
    });
    // Leaving the page is the last chance to keep what he typed.
    body.addEventListener("blur", save);
    addEventListener("pagehide", () => {
      if (body.value !== last) navigator.sendBeacon?.(
        `/notes/${body.dataset.note}`,
        new Blob([JSON.stringify({ body: body.value })], { type: "application/json" }));
    });
  }
}

/* ------------------------------------------------------- what he brings along */
{
  /* Attach then type, not the reverse. The file is uploaded the moment it is
     picked and held against the thread, so it survives him changing his mind
     about the wording, and the next message carries it. */
  const input = $("#attach");
  const holder = $("#waiting");
  const box = input?.closest(".attach");

  const chip = (file) => {
    const el = document.createElement("span");
    el.className = "chip waiting-one";
    el.dataset.attachment = file.id;
    const name = document.createElement("span");
    name.className = "n";
    name.textContent = file.filename;
    const x = document.createElement("button");
    x.type = "button"; x.className = "x"; x.textContent = "\u00d7";
    x.setAttribute("aria-label", `Remove ${file.filename}`);
    el.append(name, x);
    return el;
  };

  input?.addEventListener("change", async () => {
    if (!input.files?.length) return;
    const data = new FormData();
    for (const file of input.files) data.append("files", file);
    box?.classList.add("busy");
    try {
      const res = await send(`${location.pathname}/attach`, { method: "POST", body: data });
      const out = await res.json();
      (out.attached || []).forEach((f) => holder?.append(chip(f)));
      if (holder && holder.children.length) holder.hidden = false;
      // A refusal explains itself, once, where he can see it.
      (out.refused || []).forEach((r) => {
        const el = document.createElement("span");
        el.className = "chip waiting-one";
        el.textContent = r.why;
        holder?.append(el);
        holder.hidden = false;
        setTimeout(() => el.remove(), 6000);
      });
    } catch (e) {
      /* the sheet handled it, or it genuinely failed */
    } finally {
      box?.classList.remove("busy");
      input.value = "";
    }
  });

  holder?.addEventListener("click", async (e) => {
    const x = e.target.closest(".x");
    if (!x) return;
    const el = x.closest("[data-attachment]");
    try { await post(`/chat/attachments/${el.dataset.attachment}/remove`); } catch (err) {}
    el.remove();
    if (holder && !holder.children.length) holder.hidden = true;
  });
}

/* ------------------------------------------------- which model, and where it goes */
{
  /* The note is not decoration. It is the only place the interface says out
     loud whether what he is about to type leaves the building, and that is the
     entire reason for offering a local option at all. */
  const pick = $("#modelpick");
  const note = $("#modelnote");
  const wrap = pick?.closest(".modelwrap");
  pick?.addEventListener("change", async () => {
    const chosen = pick.value;
    const option = pick.selectedOptions[0];
    if (note) note.textContent = option?.dataset.note || "";
    if (wrap) wrap.dataset.model = chosen;
    try {
      await post(`/chat/${pick.dataset.thread}/model`, { model: chosen });
    } catch (e) {
      if (note) note.textContent = "Could not change the model.";
    }
  });
}

/* ------------------------------------------------------- documents he asks for */
{
  /* The files sheet. Opening it must not move the writing bar, which is why the
     list is a sheet over the top rather than a panel that pushes it. */
  const sheet = $("#filesheet");
  const open = (on) => {
    if (!sheet) return;
    sheet.hidden = !on;
    document.documentElement.classList.toggle("sheet-open", on);
    if (on) sheet.querySelector(".madefile, #filesheet-close")?.focus();
  };
  $("#filesbtn")?.addEventListener("click", () => open(true));
  $("#filesheet-close")?.addEventListener("click", () => open(false));
  sheet?.addEventListener("click", (e) => { if (e.target === sheet) open(false); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && sheet && !sheet.hidden) open(false);
  });

  /* Save as. Building a real document takes a few seconds, so the control says
     so rather than sitting there looking broken -- which is what he was
     pressing Return at, last time something took a while with no sign of it. */
  $$(".saveas-pick").forEach((pick) => {
    pick.addEventListener("change", async () => {
      const fmt = pick.value;
      if (!fmt) return;
      const id = Number(pick.dataset.message);
      const note = $(`[data-saymsg="${id}"]`);
      const say = (t) => { if (note) note.textContent = t || ""; };
      pick.disabled = true;
      say("Building\u2026");
      try {
        const res = await post(`${location.pathname}/document`,
                               { format: fmt, message_id: id });
        say(`Made ${res.made.filename}`);
        // Reload so the file appears in the thread's file list, where he will
        // look for it again tomorrow.
        setTimeout(() => location.reload(), 600);
      } catch (e) {
        say(e.data?.detail || "Could not build that one.");
        pick.disabled = false;
        pick.value = "";
      }
    });
  });
}

/* --------------------------------------------------------- the Friday note */
{
  const card = $("#weeknote");
  const week = card?.dataset.week;
  const bodyEl = $("#wn-body");
  const msg = $("#wn-msg");
  const say = (t) => { if (msg) { msg.textContent = t || "";
                                  if (t) setTimeout(() => (msg.textContent = ""), 3000); } };

  const bullets = (part) => Array.from(
    bodyEl?.querySelectorAll(`section[data-part="${part}"] li`) || [],
    (li) => li.textContent.trim()).filter(Boolean);

  /* The text comes from the server rather than from the page, so what he pastes
     into the email is what was actually stored, not whatever the DOM looks like
     mid-edit. */
  $("#wn-copy")?.addEventListener("click", async () => {
    try {
      const res = await fetch(`/week/${week}/text`);
      if (!res.ok) throw new Error("not ok");
      const { text } = await res.json();
      await navigator.clipboard.writeText(text);
      say("Copied");
    } catch (e) {
      // clipboard access is refused in a few contexts; say what to do instead.
      say("Could not copy. Select the text and copy it by hand.");
    }
  });

  const edit = $("#wn-edit");
  edit?.addEventListener("click", async () => {
    const editing = bodyEl.getAttribute("contenteditable") === "true";
    if (!editing) {
      bodyEl.setAttribute("contenteditable", "true");
      edit.textContent = "Save";
      bodyEl.focus();
      return;
    }
    bodyEl.setAttribute("contenteditable", "false");
    edit.textContent = "Edit";
    try {
      await post(`/week/${week}/edit`, { done: bullets("done"), next: bullets("next") });
      say("Saved");
    } catch (e) { say("Could not save that."); }
  });

  /* His own words. The one control here that writes over what is shown, so it
     says what it is doing before and after, and the built note is never lost:
     this saves into the edit slot, exactly where the Edit button saves. */
  const wordsOpen = $("#wn-words-open");
  const wordsBox = $("#wn-words-box");
  const wordsText = $("#wn-text");
  const wordsGo = $("#wn-words-go");
  const wordsMsg = $("#wn-words-msg");
  const wordsSay = (t) => { if (wordsMsg) { wordsMsg.textContent = t || "";
                            if (t) setTimeout(() => (wordsMsg.textContent = ""), 4000); } };

  wordsOpen?.addEventListener("click", () => {
    const shut = wordsBox.hidden;
    wordsBox.hidden = !shut;
    wordsOpen.setAttribute("aria-expanded", String(shut));
    if (shut) wordsText?.focus();
  });
  $("#wn-words-cancel")?.addEventListener("click", () => {
    wordsBox.hidden = true;
    wordsOpen?.setAttribute("aria-expanded", "false");
  });

  wordsGo?.addEventListener("click", async () => {
    const text = (wordsText?.value || "").trim();
    if (!text) { wordsSay("Write something first."); wordsText?.focus(); return; }
    wordsGo.disabled = true;
    wordsText.disabled = true;
    const was = wordsGo.textContent;
    wordsGo.textContent = "Laying it out\u2026";
    try {
      await post(`/week/${week}/words`, { text });
      location.reload();
    } catch (e) {
      wordsSay(e.data?.detail || "Could not lay that out just now.");
      wordsGo.disabled = false;
      wordsText.disabled = false;
      wordsGo.textContent = was;
    }
  });

  const again = $("#wn-again");
  again?.addEventListener("click", async () => {
    // Said plainly, because it is the one button here that destroys something.
    if (bodyEl?.dataset.edited === "1" &&
        !confirm("Writing it again replaces what you edited. Carry on?")) return;
    again.disabled = true;
    const was = again.textContent;
    again.textContent = "Writing\u2026";
    try {
      await post(`/week/${week}/again`, {});
      location.reload();
    } catch (e) {
      say("Could not write it again just now.");
      again.disabled = false;
      again.textContent = was;
    }
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
