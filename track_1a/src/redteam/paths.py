"""Where runs are. A run made on this machine is written to runs/; the recorded runs that the
findings and the report rest on also ship with the repository in data/runs/. A run is looked up in
runs/ first.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
SHIPPED = ROOT / "data" / "runs"
RUN_ID = re.compile(r"[\w-]+")  # a plain folder name, so an id cannot point outside the run folders


def latest() -> str | None:
    """The id of the newest run made on this machine."""
    path = RUNS / "latest"
    return path.read_text().strip() if path.exists() else None


def run_dir(run_id: str) -> Path | None:
    """The folder of a run ("latest" for the newest local one) that holds its event log, or None."""
    if run_id == "latest":
        run_id = latest() or ""
    if not RUN_ID.fullmatch(run_id):
        return None
    return next((root / run_id for root in (RUNS, SHIPPED)
                 if (root / run_id / "events.jsonl").is_file()), None)


def run_dirs() -> list[Path]:
    """Every run with an event log, sorted by id, each id once and from where run_dir finds it."""
    found = {}
    for root in (SHIPPED, RUNS):  # runs/ last, so its copy of an id wins
        for events in root.glob("*/events.jsonl"):
            found[events.parent.name] = events.parent
    return [found[run_id] for run_id in sorted(found)]
