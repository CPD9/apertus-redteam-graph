"""Dashboard server (stdlib). Serves web/ plus a small JSON API; can start runs in a thread.

GET  /api/state?run=<id|latest>   events, findings, control, rejudge summary, hypothesis texts and
                                   the hypotheses whose answers could not be recounted (dashboard.py)
GET  /api/runs                     runs newest first: id, label, target model, backend, written
                                   (findings files the harness wrote, before the recount)
POST /api/run                      start a run in the background
GET  /api/review/sample?run=<id|latest>&n=50   judge decisions for blind human labelling
POST /api/review/label             {id, human_violation, note}
GET  /api/review/agreement         judge-human agreement (n, raw, Cohen's kappa)
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
LOOPBACK = {"127.0.0.1", "localhost"}


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
        if u.path == "/api/review/sample":
            q = parse_qs(u.query)
            try:
                run_id = review.resolve_run(q.get("run", ["latest"])[0])
                items = review.sample(run_id, int(q.get("n", ["50"])[0]))
            except (ValueError, OSError) as e:
                return self._json({"error": str(e)}, 404)
            done = {l["id"] for l in review.labels()}
            return self._json({"run_id": run_id, "items": items,
                               "labelled": [it["id"] for it in items if it["id"] in done]})
        if u.path == "/api/review/agreement":
            return self._json(review.agreement())
        return super().do_GET()

    def do_POST(self):
        if not self._from_here():
            return self._json({"error": "only the dashboard's own pages may post here"}, 403)
        path = urlparse(self.path).path
        if path.startswith("/api/avatar/"):
            return self._save_avatar(path.rsplit("/", 1)[1])
        if path == "/api/review/label":
            return self._save_label()
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

    def _save_label(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except ValueError:
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("human_violation"), bool):
            return self._json({"error": "human_violation must be true or false"}, 400)
        try:
            saved = review.save_label(str(body.get("id", "")), body["human_violation"],
                                      str(body.get("note", "")))
        except (ValueError, OSError) as e:
            return self._json({"error": str(e)}, 404)
        return self._json({"saved": saved, "agreement": review.agreement()})


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
