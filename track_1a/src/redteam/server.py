"""Dashboard server (stdlib). Serves web/ plus a small JSON API; can start runs in a thread.

GET  /api/state?run=<id|latest>   events + summary + findings of a run
GET  /api/runs                     run ids, newest first
POST /api/run                      start a run in the background
GET  /api/review/sample?run=<id|latest>&n=50   judge decisions for blind human labelling
POST /api/review/label             {id, human_violation, note}
GET  /api/review/agreement         judge-human agreement (n, raw, Cohen's kappa)
Binds 127.0.0.1 by default (HOST env overrides, e.g. 0.0.0.0 inside Docker).
"""
from __future__ import annotations

import base64
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import review
from . import run as run_mod

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
_running = threading.Lock()
AGENTS = {"attacker", "mutator", "target", "judge", "verifier", "scribe"}


def state(run_id: str) -> dict:
    if run_id == "latest":
        p = RUNS / "latest"
        if not p.exists():
            return {"run_id": None, "events": [], "findings": [], "running": _running.locked()}
        run_id = p.read_text().strip()
    d = RUNS / run_id
    ev = d / "events.jsonl"
    events = [json.loads(l) for l in ev.read_text().splitlines() if l.strip()] if ev.exists() else []
    findings = [json.loads(f.read_text()) for f in sorted((d / "findings").glob("*.json"))] \
        if (d / "findings").exists() else []
    return {"run_id": run_id, "events": events, "findings": findings, "running": _running.locked()}


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

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/state":
            return self._json(state(parse_qs(u.query).get("run", ["latest"])[0]))
        if u.path == "/api/runs":
            ids = sorted([p.name for p in RUNS.iterdir() if p.is_dir()], reverse=True) if RUNS.exists() else []
            return self._json(ids)
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
