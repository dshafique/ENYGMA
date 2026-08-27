"""A stand-in HiNotes server, so the poller can be developed without the recorder.

Runs on: any machine.

    python3 tools/fake_hinotes.py            # healthy, two recordings
    python3 tools/fake_hinotes.py --dead     # a dead token: HTTP 200 + the envelope

Point the app at it with:

    ENYGMA_HINOTES_BASE=http://127.0.0.1:4099
    ENYGMA_HINOTES_TOKEN=anything

The --dead mode exists because that is the failure worth rehearsing. It is the one
that looks like success.
"""
import argparse, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

DEAD = {"error": 10000, "message": "session_timeout", "data": None}
RECORDINGS = [
    {"noteId": "n-2026-08-21-a", "noteTitle": "Quarterly review with Meridian.hda",
     "createTime": "2026-08-21 10:30:00", "duration": 2537},
    {"noteId": "n-2026-08-21-b", "noteTitle": "Onboarding sync with Priya.hda",
     "createTime": "2026-08-21 09:15:00", "duration": 1084},
]
MP3 = b"ID3" + b"\x00" * 512


class Handler(BaseHTTPRequestHandler):
    dead = False

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        # Note what is NOT checked here: the token. A real dead token still
        # returns 200, which is exactly what --dead reproduces.
        if self.dead:
            return self._json(DEAD)
        if url.path == "/v1/note/recording/list":
            return self._json({"error": 0, "data": RECORDINGS})
        if url.path == "/v2/note/audio/download":
            note = parse_qs(url.query).get("noteId", [""])[0]
            if not any(r["noteId"] == note for r in RECORDINGS):
                return self._json(DEAD)
            self.send_response(200)
            self.send_header("content-type", "audio/mpeg")
            self.send_header("content-length", str(len(MP3)))
            self.end_headers()
            self.wfile.write(MP3)
            return
        self._json({"error": 404, "message": "not found"}, 404)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4099)
    ap.add_argument("--dead", action="store_true", help="simulate an expired token")
    args = ap.parse_args()
    Handler.dead = args.dead
    print(f"fake HiNotes on :{args.port}  dead={args.dead}")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
