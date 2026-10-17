"""Human review of judge decisions: blind labelling and judge-human agreement (Cohen's kappa).

Item ids are "<run_id>:<event line>", so a label can be resolved back to its event after a restart.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from .run import load_hypotheses

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
LABELS = ROOT / "tests" / "judge_cases.jsonl"


def resolve_run(run_id: str) -> str:
    if run_id == "latest":
        run_id = (RUNS / "latest").read_text().strip()
    # Compare against real directory names so a crafted id cannot escape runs/.
    if run_id not in {p.name for p in RUNS.iterdir()} or not (RUNS / run_id / "events.jsonl").exists():
        raise ValueError(f"unknown run {run_id!r}")
    return run_id


def items(run_id: str) -> list[dict]:
    """Every judge verdict of a run, joined with the prompt and answer it judged."""
    refs = {h["id"]: h["reference"] for h in load_hypotheses()}
    lines = (RUNS / run_id / "events.jsonl").read_text().splitlines()
    prompts, answers, out = {}, {}, []
    for i, line in enumerate(lines):
        e = json.loads(line) if line.strip() else {}
        if e.get("status") != "done":
            continue
        hyp, d = e["hypothesis"], e["data"]
        if e["node"] == "mutator":
            prompts[hyp] = d["prompts"]
        elif e["node"] == "target":
            answers[hyp, d["lang"]] = d["answer"]
        elif e["node"] == "judge":
            out.append({"id": f"{run_id}:{i}", "run_id": run_id, "hypothesis": hyp, "lang": d["lang"],
                        "reference": refs.get(hyp), "prompt": prompts.get(hyp, {}).get(d["lang"]),
                        "answer": answers.get((hyp, d["lang"])),
                        "judge_violation": bool(d["violation"]), "judge_reason": d.get("reason", "")})
    return out


def _spread(pool: list[dict], k: int, rng: random.Random) -> list[dict]:
    """Take k items round-robin over languages, so no language dominates the sample."""
    by_lang = {}
    for it in pool:
        by_lang.setdefault(it["lang"], []).append(it)
    queues = [rng.sample(v, len(v)) for _, v in sorted(by_lang.items())]
    picked = []
    while len(picked) < k and any(queues):
        picked += [q.pop() for q in queues if q][:k - len(picked)]
    return picked


def sample(run_id: str, n: int = 50, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    pool = items(resolve_run(run_id))
    hits = [it for it in pool if it["judge_violation"]]
    clean = [it for it in pool if not it["judge_violation"]]
    # Violations are the rarer class; give clean items whatever share they cannot fill.
    n_hits = min(len(hits), n // 2)
    n_clean = min(len(clean), n - n_hits)
    n_hits = min(len(hits), n - n_clean)
    chosen = _spread(hits, n_hits, rng) + _spread(clean, n_clean, rng)
    rng.shuffle(chosen)
    return chosen


def find(item_id: str) -> dict:
    run_id, _, _ = item_id.rpartition(":")
    for it in items(resolve_run(run_id)):
        if it["id"] == item_id:
            return it
    raise ValueError(f"unknown item {item_id!r}")


def labels() -> list[dict]:
    lines = LABELS.read_text().splitlines() if LABELS.exists() else []
    return [json.loads(l) for l in lines if l.strip()]


def save_label(item_id: str, human_violation: bool, note: str = "", item: dict | None = None) -> bool:
    """Append one label; returns False if this item was already labelled."""
    if any(l["id"] == item_id for l in labels()):
        return False
    row = {**(item or find(item_id)), "human_violation": bool(human_violation), "note": note,
           "labelled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with LABELS.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """None when undefined: no pairs, or both raters gave one constant label (expected agreement 1)."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    pa = sum(bool(a) for a, _ in pairs) / n
    pb = sum(bool(b) for _, b in pairs) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def agreement() -> dict:
    # Seed cases have no judge verdict (judge_violation is null) and cannot count towards kappa.
    pairs = [(l["judge_violation"], l["human_violation"]) for l in labels()
             if l.get("judge_violation") is not None and l.get("human_violation") is not None]
    raw = sum(a == b for a, b in pairs) / len(pairs) if pairs else None
    return {"n": len(pairs), "raw_agreement": raw, "kappa": cohen_kappa(pairs)}
