"""Dashboard server (stdlib). Serves web/ plus a small JSON API; can start runs in a thread.

GET  /api/state?run=<id|latest>   events, findings, control, rejudge summary and hypothesis texts
GET  /api/runs                     runs newest first: id, label, target model, backend, flagged
                                   (findings the harness wrote, before the recount)
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
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import answers, review
from . import run as run_mod
from .cache import CACHE_DIR
from .graph import Config

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
CACHE = CACHE_DIR
RUN_ID = re.compile(r"[\w-]+")
_running = threading.Lock()
AGENTS = {"attacker", "mutator", "target", "judge", "verifier", "scribe"}
HYPOTHESIS_FIELDS = ("domain", "hypothesis", "reference", "harm", "sources")


def _json_file(path: Path, default):
    # Files of a live run can be caught half-written; treat them as not there yet.
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def _resolve(run_id: str) -> str | None:
    if run_id == "latest":
        latest = RUNS / "latest"
        run_id = latest.read_text().strip() if latest.exists() else ""
    return run_id if RUN_ID.fullmatch(run_id) and (RUNS / run_id).is_dir() else None


def hypotheses() -> dict:
    return {h["id"]: {k: h.get(k) for k in HYPOTHESIS_FIELDS} for h in run_mod.load_hypotheses()}


def state(run_id: str) -> dict:
    run_id = _resolve(run_id)
    shared = {"run_id": run_id, "running": _running.locked(), "hypotheses": hypotheses()}
    if run_id is None:
        return {**shared, "events": [], "findings": [], "control": [], "rejudge": None}
    d = RUNS / run_id
    events = _events(d / "events.jsonl")
    verified = _recount(d, events)
    retracted = {h for h, v in verified.items() if v["overall"] < Config.min_rate}
    findings = [_json_file(p, None) for p in sorted(d.glob("findings/*.json"))]
    rejudge = _json_file(d / "rejudge.json", None)
    return {**shared,
            "events": events,
            "findings": [f for f in findings if f and f["issue_summary"]["title"] not in retracted],
            "control": _recount_control(d, _json_file(d / "control.json", [])),
            "rejudge": {k: rejudge.get(k) for k in ("n", "kappa", "raw_agreement")} if rejudge else None}


_counted: dict[tuple, dict] = {}
_neutral: dict[tuple, dict] = {}


def _recount(run_dir: Path, events: list[dict]) -> dict[str, dict]:
    """Count verifier results like the findings do (answers.Answer.confirmed), in place, and return
    them by hypothesis. Memoised per log size: replaying is not free. Early runs logged only
    per-language rates and are left as logged."""
    verified = {e["hypothesis"]: e["data"] for e in events
                if e["node"] == "verifier" and e["status"] == "done"}
    key = (run_dir.name, len(events))
    counted = _counted.get(key)
    if counted is None:
        refs = {h["id"]: h for h in run_mod.load_hypotheses()}
        answers.recount(run_dir, verified, refs, CACHE)
        counted = {h: dict(d) for h, d in verified.items()}
        _counted.clear()  # one run at a time is enough for the dashboard
        _counted[key] = counted
    for h, data in counted.items():
        verified[h].update(data)
    return verified


def _recount_control(run_dir: Path, rows: list[dict]) -> list[dict]:
    """Count the neutral control the same way, in place; rows the cache cannot replay keep their
    logged rates. Memoised per number of rows."""
    key = (run_dir.name, len(rows))
    shares = _neutral.get(key)
    if shares is None:
        refs = {h["id"]: h for h in run_mod.load_hypotheses()}
        shares = answers.control_shares(run_dir, rows, refs, CACHE)
        _neutral.clear()  # one run at a time, as above
        _neutral[key] = shares
    for row in rows:
        if row["id"] in shares:
            premise, neutral = shares[row["id"]]
            row["premise_rate"] = premise.rate
            row["neutral_rate"], row["neutral_ci95"] = neutral.rate, list(neutral.ci95)
    return rows


def _start_event(events: Path) -> dict:
    with events.open() as f:
        try:
            return json.loads(f.readline())
        except ValueError:
            return {}


def runs() -> list[dict]:
    rows = []
    for events in sorted(RUNS.glob("*/events.jsonl"), reverse=True):
        d = events.parent
        if d.name.startswith("_"):  # aborted or archived by hand
            continue
        start = _start_event(events)
        rows.append({"id": d.name, "label": (start.get("data") or {}).get("label") or "",
                     "model": start.get("model"), "backend": start.get("backend"),
                     "flagged": len(list(d.glob("findings/*.json")))})
    return rows


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
            return self._json(runs())
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
