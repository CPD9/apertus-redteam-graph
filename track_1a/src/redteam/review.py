"""Human review of judge decisions: blind labelling and judge-human agreement (Cohen's kappa).

Item ids are "<run_id>:<event line>", so a label can be resolved back to its event after a restart.
The event log keeps only the start of each answer; reviewers see the whole answer, replayed from
the LLM cache.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

from . import agents, paths
from .cache import CACHE_DIR, Cached, CacheMiss
from .events import first_event, numbered_events
from .graph import PROBE_LOGGED_CHARS
from .run import load_hypotheses

LABELS = paths.ROOT / "tests" / "judge_cases.jsonl"


def run_dir(run_id: str) -> Path:
    """A local run or a recorded one in data/runs/ ("latest" for the newest local run)."""
    d = paths.run_dir(run_id)
    if d is None:
        raise ValueError("no run on this machine yet" if run_id == "latest"
                         else f"unknown run {run_id!r}")
    return d


def resolve_run(run_id: str) -> str:
    return run_dir(run_id).name


def items(run_id: str) -> list[dict]:
    """Every judge verdict of a run, joined with the prompt and answer it judged."""
    refs = {h["id"]: h["reference"] for h in load_hypotheses()}
    folder = run_dir(run_id)
    run_id = folder.name
    prompts, answers, out = {}, {}, []
    for i, e in numbered_events(folder / "events.jsonl"):
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


def in_full(run_id: str, chosen: list[dict]) -> list[dict]:
    """The chosen items with each answer replayed whole from the LLM cache, asked as the run asked
    it: seed 0, temperature 0 and the run's system prompt. Only the chosen ones, because a replay
    is a cache lookup per item."""
    start = first_event(run_dir(run_id) / "events.jsonl")
    target = Cached(None, start.get("model", ""), replay=True, root=CACHE_DIR)
    system = start.get("data", {}).get("system")
    return [{**it, "answer": full_answer(target, it, system)} for it in chosen]


def full_answer(target: Cached, item: dict, system: str | None) -> str | None:
    """The whole answer, or, when the cache does not hold it (mock runs), the logged start with a
    note that it was cut."""
    try:
        return agents.target(target, item["prompt"], 0, 0.0, system)
    except CacheMiss:
        logged = item["answer"]
        if logged and len(logged) >= PROBE_LOGGED_CHARS:
            return logged + f" [cut: the event log keeps {PROBE_LOGGED_CHARS} characters]"
        return logged


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
    pool = items(run_id)
    hits = [it for it in pool if it["judge_violation"]]
    clean = [it for it in pool if not it["judge_violation"]]
    # Violations are the rarer class; give clean items whatever share they cannot fill.
    n_hits = min(len(hits), n // 2)
    n_clean = min(len(clean), n - n_hits)
    n_hits = min(len(hits), n - n_clean)
    chosen = _spread(hits, n_hits, rng) + _spread(clean, n_clean, rng)
    rng.shuffle(chosen)
    return in_full(run_id, chosen)


def find(item_id: str) -> dict:
    run_id, _, _ = item_id.rpartition(":")
    for it in items(run_id):
        if it["id"] == item_id:
            return in_full(run_id, [it])[0]
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
