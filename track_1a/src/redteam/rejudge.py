"""Second opinion: re-judge every answer of a run with the independently worded judge and report
how often the two judges agree (Cohen's kappa). Answers come from the run's event log, replayed in
full from the LLM cache: the log keeps only the start of each answer. It writes
runs/<run_id>/rejudge.json; the recorded runs in data/runs/ keep the one they ship with.

    PYTHONPATH=src python -m redteam.rejudge --run RUN_ID
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import agents, llm as llm_mod, paths
from .cache import CACHE_DIR, Cached, CacheMiss
from .events import read_events
from .graph import Config
from .judge import second_opinion
from .review import cohen_kappa
from .run import load_hypotheses


def judged_cells(run_dir: Path, cache_root: Path = CACHE_DIR) -> list[dict]:
    """Every (prompt, answer, first verdict) the run produced, probe phase and verifier grid. The
    probe phase asks each prompt once at temperature 0, the verifier once per seed."""
    events = read_events(run_dir / "events.jsonl")
    model, system = events[0]["model"], events[0]["data"].get("system")
    target = Cached(None, model, replay=True, root=cache_root)

    def cell(phase, hyp, lang, prompt, seed, temperature, first):
        answer = agents.target(target, prompt, seed, temperature, system)
        return {"phase": phase, "hypothesis": hyp, "lang": lang, "prompt": prompt,
                "answer": answer, "first": first}

    prompts, cells = {}, []
    for e in events:
        hyp, d, step = e["hypothesis"], e["data"], (e["node"], e["status"])
        if step == ("mutator", "done"):
            prompts[hyp] = d["prompts"]
        elif step == ("judge", "done"):
            cells.append(cell("probe", hyp, d["lang"], prompts[hyp][d["lang"]], 0, 0.0,
                              d["violation"]))
        elif step == ("verifier", "progress"):
            cells.append(cell("verifier", hyp, d["lang"], prompts[hyp][d["lang"]], d["seed"],
                              Config.temperature, d["violation"]))
    return cells


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default=None, help="run id (default: runs/latest)")
    a = ap.parse_args(argv)
    run_dir = paths.run_dir(a.run or "latest")
    if run_dir is None:
        ap.error(f"no run {a.run or 'latest'} in runs/ or data/runs/")
    run_id = run_dir.name
    if run_dir.parent == paths.SHIPPED:
        ap.error(f"{run_id} is a recorded run in data/runs/; its rejudge.json ships with the "
                 "repository and is not rewritten. Copy the folder to runs/ to judge it again "
                 "there")
    refs = {h["id"]: h for h in load_hypotheses()}
    try:
        cells = [c for c in judged_cells(run_dir, CACHE_DIR) if c["hypothesis"] in refs]
    except CacheMiss as e:
        ap.error(f"{e}; the answers of run {run_id} are replayed from {CACHE_DIR}")

    llm = llm_mod.detect()
    with ThreadPoolExecutor(16) as pool:
        second = list(pool.map(lambda c: second_opinion(llm, refs[c["hypothesis"]], c["prompt"],
                                                        c["answer"]), cells))
    for c, s in zip(cells, second):
        c["second"] = s["violation"]
    pairs = [(c["first"], c["second"]) for c in cells]
    report = {"run_id": run_id, "n": len(pairs), "kappa": cohen_kappa(pairs),
              "raw_agreement": sum(x == y for x, y in pairs) / len(pairs) if pairs else None,
              "cells": cells}
    (run_dir / "rejudge.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{run_id}: {report['n']} answers, agreement {report['raw_agreement']:.0%}, "
          f"kappa {report['kappa']:.2f}" if pairs else f"{run_id}: no judged answers found")
    return report


if __name__ == "__main__":
    main()
