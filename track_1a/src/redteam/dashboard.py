"""What the dashboard shows of a run: its events with the verifier results counted like the
findings, its findings, the neutral control, the second judge's agreement and the hypotheses.

The server asks for this every few hundred milliseconds while a run is live, so the hypothesis
banks and the recounts are kept until the files they come from change.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import answers, paths
from . import run as run_mod
from .cache import CACHE_DIR
from .events import first_event, read_events
from .graph import Config

CACHE = CACHE_DIR
HYPOTHESIS_FIELDS = ("title", "domain", "hypothesis", "reference", "harm", "sources")


def _json_file(path: Path, default):
    # Files of a live run can be caught half-written; treat them as not there yet.
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# kind -> (key, value), computed again when the key changes. One entry per kind is enough: the
# dashboard shows one run at a time.
_memo: dict[str, tuple] = {}


def _memoised(kind: str, key: tuple, compute):
    held = _memo.get(kind)
    if held is None or held[0] != key:
        held = _memo[kind] = (key, compute())
    return held[1]


def bank() -> dict[str, dict]:
    """Every hypothesis by id, read again only when a bank file changes."""
    key = tuple((f.name, f.stat().st_mtime_ns) for f in sorted(run_mod.HYPOTHESES.glob("*.json")))
    return _memoised("bank", key, lambda: {h["id"]: h for h in run_mod.load_hypotheses()})


def hypotheses() -> dict:
    return {i: {k: h.get(k) for k in HYPOTHESIS_FIELDS} for i, h in bank().items()}


def state(run_id: str) -> dict:
    """The run ("latest" for the newest local one); run_id is None when there is no such run."""
    d = paths.run_dir(run_id)
    shared = {"run_id": d.name if d else None, "hypotheses": hypotheses()}
    if d is None:
        return {**shared, "events": [], "findings": [], "uncounted": [], "control": [],
                "rejudge": None}
    events = read_events(d / "events.jsonl")
    verified, uncounted = _recount(d, events)
    below = {h for h, v in verified.items() if v["overall"] < Config.min_rate}
    rejudge = _json_file(d / "rejudge.json", None)
    agreement = {k: rejudge.get(k) for k in ("n", "kappa", "raw_agreement")} if rejudge else None
    return {**shared, "events": events, "findings": _findings(d, events, below),
            "uncounted": sorted(uncounted), "control": _recount_control(d), "rejudge": agreement}


def _findings(run_dir: Path, events: list[dict], below: set[str]) -> list[dict]:
    """The findings files of the hypotheses the run wrote up, each named after its hypothesis (a
    file's title may be a sentence), minus those the recount puts below the bar. The copies of the
    recorded runs in data/runs/ leave the files out, so a written-up hypothesis without one is
    listed by its id alone and the dashboard builds its card from the events."""
    files = {p.stem: p for p in run_dir.glob("findings/*.json")}
    written = {e["hypothesis"] for e in events if e["node"] == "scribe" and e["status"] == "done"}
    return [{**(_json_file(files[h], {}) if h in files else {}), "hypothesis": h}
            for h in sorted((written | set(files)) - below)]


def _recount(run_dir: Path, events: list[dict]) -> tuple[dict[str, dict], set[str]]:
    """Verifier results by hypothesis, counted like the findings (answers.Answer.confirmed), and
    the hypotheses that could not be counted, which keep the share the judge flagged. Runs log the
    counted results themselves since the counting rule; older runs are replayed from the LLM cache,
    which is not free, so only when another hypothesis has been verified."""
    verified = {e["hypothesis"]: e["data"] for e in events
                if e["node"] == "verifier" and e["status"] == "done"}

    def count():
        older = {h: data for h, data in verified.items() if "counted" not in data}
        uncounted = answers.recount(run_dir, older, bank(), CACHE)
        return {h: {**data, **data.get("counted", {})} for h, data in verified.items()}, uncounted

    counted, uncounted = _memoised("recount", (str(run_dir), len(verified)), count)
    for h, data in counted.items():
        verified[h].update(data)
    return verified, uncounted


def _recount_control(run_dir: Path) -> list[dict]:
    """The neutral control counted the same way; rows the cache cannot replay keep their logged
    rates. Replayed again only when control.json changes."""
    path = run_dir / "control.json"
    rows = _json_file(path, [])
    if not rows:
        return []
    key = (str(path), path.stat().st_mtime_ns, len(rows))
    shares = _memoised("control", key,
                       lambda: answers.control_shares(run_dir, rows, bank(), CACHE))
    for row in rows:
        if row["id"] in shares:
            premise, neutral = shares[row["id"]]
            row["premise_rate"] = premise.rate
            row["neutral_rate"], row["neutral_ci95"] = neutral.rate, list(neutral.ci95)
    return rows


def runs() -> list[dict]:
    """Every run newest first, with the number of findings files the harness wrote for it."""
    rows = []
    for d in reversed(paths.run_dirs()):
        if d.name.startswith("_"):  # aborted or archived by hand
            continue
        start = first_event(d / "events.jsonl")
        rows.append({"id": d.name, "label": (start.get("data") or {}).get("label") or "",
                     "model": start.get("model"), "backend": start.get("backend"),
                     "written": len(list(d.glob("findings/*.json")))})
    return rows
