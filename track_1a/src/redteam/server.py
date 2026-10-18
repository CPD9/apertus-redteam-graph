"""Dashboard server (stdlib). Serves web/ plus a small JSON API; can start runs in a thread.

GET  /api/state?run=<id|latest>   events, findings, control, rejudge summary, hypothesis texts and
                                   the hypotheses whose answers could not be recounted (dashboard.py)
GET  /api/runs                     runs newest first: id, label, target model, backend, written
                                   (findings files the harness wrote, before the recount)
POST /api/run                      start a run in the background
GET  /api/review/set?labeller=<name>   the blind judge set without the judge's verdicts, the
                                       labeller's labels and, after their reveal, the verdicts
POST /api/review/label             {labeller, id, label: asserts|does_not|cant_tell, hedged, note}
POST /api/review/reveal            {labeller}: the judge's verdicts; ends that labeller's labelling
GET  /api/review/stimuli?lang=<gsw|rm>&labeller=<name>   prompts for the native speakers' check
POST /api/review/rating            {labeller, id, label: natural|odd|not_this_language, note}
GET  /api/review/report            everything the labels of those who saw the verdicts say
                                   (python -m redteam.review)
GET  /api/studio                   whether web/studio/ holds a copy of the avatar studio, which
                                   is not in git
POST /api/avatar/<agent>           save the avatar studio's PNG for an agent
Binds 127.0.0.1 by default (HOST env overrides, e.g. 0.0.0.0 inside Docker). POSTs are refused
unless they come from this server's own pages on 127.0.0.1 or localhost.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import dashboard, review
from . import run as run_mod
from .paths import ROOT

_running = threading.Lock()
AGENTS = {"attacker", "mutator", "target", "judge", "verifier", "scribe"}
STUDIO = ROOT / "web" / "studio" / "dot-avatar-maker.html"
LOOPBACK = {"127.0.0.1", "localhost"}
REVIEW_GET = {
    "/api/review/set": lambda q: review.session(q.get("labeller")),
    "/api/review/stimuli": lambda q: review.stimuli_session(q.get("lang"), q.get("labeller")),
    "/api/review/report": lambda q: review.report(),
}
REVIEW_POST = {
    "/api/review/label": lambda b: review.save_label(b.get("labeller"), b.get("id"),
                                                     b.get("label"), b.get("note"),
                                                     b.get("hedged", False)),
    "/api/review/reveal": lambda b: review.reveal(b.get("labeller")),
    "/api/review/rating": lambda b: review.save_rating(b.get("labeller"), b.get("id"),
                                                       b.get("label"), b.get("note")),
}


def loopback(value: str, port: int) -> bool:
    """Whether an Origin ("http://localhost:8765") or Host ("127.0.0.1:8765") header names this
    server's port on 127.0.0.1 or localhost."""
    u = urlparse(value if "://" in value else "//" + value)
    try:
        return u.scheme in ("", "http") and u.hostname in LOOPBACK and (u.port or 80) == port
    except ValueError:  # a port that is not a number
        return False


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "web"), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _from_here(self) -> bool:
        """Browsers name the page behind a POST in Origin, so a page from elsewhere cannot start
        runs or write files here. Without Origin (curl, scripts) the Host must be this server,
        which a page that rebinds its own name to 127.0.0.1 cannot fake."""
        port, origin = self.server.server_address[1], self.headers.get("Origin")
        return loopback(origin if origin is not None else self.headers.get("Host", ""), port)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/state":
            run_id = parse_qs(u.query).get("run", ["latest"])[0]
            return self._json({**dashboard.state(run_id), "running": _running.locked()})
        if u.path == "/api/runs":
            return self._json(dashboard.runs())
        if u.path in REVIEW_GET:
            query = {k: v[0] for k, v in parse_qs(u.query).items()}
            return self._review(REVIEW_GET[u.path], query)
        if u.path == "/api/studio":
            return self._json({"present": STUDIO.is_file()})
        return super().do_GET()

    def do_POST(self):
        if not self._from_here():
            return self._json({"error": "only the dashboard's own pages may post here"}, 403)
        path = urlparse(self.path).path
        if path.startswith("/api/avatar/"):
            return self._save_avatar(path.rsplit("/", 1)[1])
        if path in REVIEW_POST:
            return self._review(REVIEW_POST[path], self._body())
        if path != "/api/run":
            return self._json({"error": "not found"}, 404)
        if not _running.acquire(blocking=False):
            return self._json({"error": "a run is already in progress"}, 409)

        def work():
            try:
                run_mod.main([])
            finally:
                _running.release()
        threading.Thread(target=work, daemon=True).start()
        return self._json({"started": True})

    def _save_avatar(self, agent: str):
        """Body: a PNG data URL from the avatar studio's window.__dot.snapshot()."""
        if agent not in AGENTS:
            return self._json({"error": f"unknown agent {agent!r}"}, 400)
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        prefix = "data:image/png;base64,"
        if not raw.startswith(prefix):
            return self._json({"error": "expected a PNG data URL"}, 400)
        png = base64.b64decode(raw[len(prefix):])
        (ROOT / "web" / "avatars" / f"{agent}.png").write_bytes(png)
        return self._json({"saved": agent, "bytes": len(png)})

    def _body(self) -> dict:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _review(self, call, arg):
        try:
            return self._json(call(arg))
        except review.Closed as e:
            return self._json({"error": str(e)}, 409)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        except (OSError, RuntimeError, KeyError) as e:  # a run or its cached answers are missing
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def main():
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8765"))
    os.environ.setdefault("REDTEAM_MOCK_DELAY", "0.04")
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        if e.errno in (48, 98):  # address in use (macOS, Linux)
            raise SystemExit(f"Port {port} is already in use. The dashboard is probably already "
                             f"running: open {url}\nTo stop it: pkill -f redteam.server  "
                             f"(or use another port: PORT=8766 make dashboard)")
        raise
    print(f"dashboard: {url}")
    server.serve_forever()


if __name__ == "__main__":
    main()
