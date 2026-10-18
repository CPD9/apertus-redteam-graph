"""The event log of a run: one JSON object per line in runs/<run_id>/events.jsonl.

The graph appends to it from several threads while the dashboard and the report read it, so a
reader can meet a line that is still being written.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class EventLog:
    def __init__(self, run_dir: Path, run_id: str, backend: str, model: str):
        self.path = run_dir / "events.jsonl"
        self.run_id, self.backend, self.model = run_id, backend, model
        self.lock = threading.Lock()  # the verifier emits from worker threads
        run_dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, node: str, status: str, data: dict | None = None, hyp: str | None = None):
        ev = {"t": round(time.time(), 3), "run_id": self.run_id, "hypothesis": hyp, "node": node,
              "status": status, "backend": self.backend, "model": self.model, "data": data or {}}
        with self.lock, self.path.open("a") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


def numbered_events(path: Path) -> list[tuple[int, dict]]:
    """Every complete event of a log with its line number, which the review's item ids use;
    skips a line that is cut off or not JSON."""
    events = []
    for i, line in enumerate(path.read_text().splitlines()):
        try:
            events.append((i, json.loads(line)))
        except ValueError:
            continue
    return events


def read_events(path: Path) -> list[dict]:
    """Every complete event of a log, skipping a line that is cut off or not JSON."""
    return [event for _, event in numbered_events(path)]


def first_event(path: Path) -> dict:
    """The graph's start event, which names the models, languages and system prompt of the run;
    empty if the log has no complete first line yet."""
    with path.open() as f:
        try:
            return json.loads(f.readline())
        except ValueError:
            return {}
