"""Second opinion: re-judge every answer of a run with the independently worded judge and report
how often the two judges agree (Cohen's kappa). Answers come from the run's event log, replayed in
full from the LLM cache: the log keeps only the start of each answer. It writes
runs/<run_id>/rejudge.json; the recorded runs in data/runs/ keep the one they ship with.

The second judge is the red-team model unless --judge-url names another OpenAI-compatible server,
such as a model of another family (key in JUDGE_API_KEY, if it needs one). It gets the same
requests, and its report goes to runs/<run_id>/rejudge_<model>.json, for recorded runs too. An
answer it cannot judge keeps second = null and stays out of kappa and agreement; the report
counts these as "unread". The red-team judge stops at the first one, as it always has.

    PYTHONPATH=src python -m redteam.rejudge --run RUN_ID [--judge-url URL [--judge-name MODEL]]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import agents, llm as llm_mod, paths
from .cache import CACHE_DIR, Cached, CacheMiss
from .events import read_events
from .graph import Config
from .judge import second_opinion
from .review import cohen_kappa
from .run import load_hypotheses

# One answer another judge can fail on without the others: a reply that still does not parse
# after the repair round, or a call that times out.
UNREAD = (ValueError, OSError)


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


def other_judge(url: str, name: str | None) -> Cached | None:
    """The judge served at url, under name or the first model it serves; None if nothing answers.
    Its calls are cached like the run's, so its verdicts replay too."""
    key = os.environ.get("JUDGE_API_KEY", "")
    served = llm_mod.probe(url, key)
    if served is None:
        return None
    model = name or served
    return Cached(llm_mod.OpenAIChat(url, model, key), model, root=CACHE_DIR)


def verdicts(llm, refs: dict[str, dict], cells: list[dict], tolerant: bool) -> list[bool | None]:
    """The second judge's flag on every cell; with tolerant, None where it could not judge one."""
    def one(c):
        try:
            return second_opinion(llm, refs[c["hypothesis"]], c["prompt"], c["answer"])["violation"]
        except UNREAD:
            if not tolerant:
                raise
            return None

    with ThreadPoolExecutor(16) as pool:
        return list(pool.map(one, cells))


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default=None, help="run id (default: runs/latest)")
    ap.add_argument("--judge-url", help="OpenAI-compatible endpoint of another second judge "
                                        "(default: the red-team model)")
    ap.add_argument("--judge-name", help="model to ask at --judge-url (default: the one it serves)")
    a = ap.parse_args(argv)
    if a.judge_name and not a.judge_url:
        ap.error("--judge-name needs --judge-url")
    run_dir = paths.run_dir(a.run or "latest")
    if run_dir is None:
        ap.error(f"no run {a.run or 'latest'} in runs/ or data/runs/")
    run_id = run_dir.name
    if run_dir.parent == paths.SHIPPED and not a.judge_url:
        ap.error(f"{run_id} is a recorded run in data/runs/; its rejudge.json ships with the "
                 "repository and is not rewritten. Copy the folder to runs/ to judge it again "
                 "there")
    refs = {h["id"]: h for h in load_hypotheses()}
    try:
        cells = [c for c in judged_cells(run_dir, CACHE_DIR) if c["hypothesis"] in refs]
    except CacheMiss as e:
        ap.error(f"{e}; the answers of run {run_id} are replayed from {CACHE_DIR}")

    if a.judge_url:
        llm = other_judge(a.judge_url, a.judge_name)
        if llm is None:
            ap.error(f"nothing answers at {a.judge_url}")
        out = paths.RUNS / run_id / f"rejudge_{re.sub(r'[^\w.-]+', '_', llm.model)}.json"
    else:
        llm, out = llm_mod.detect(), run_dir / "rejudge.json"
    for c, second in zip(cells, verdicts(llm, refs, cells, tolerant=bool(a.judge_url))):
        c["second"] = second
    pairs = [(c["first"], c["second"]) for c in cells if c["second"] is not None]
    report = {"run_id": run_id, "judge": getattr(llm, "red_model", llm.model), "n": len(pairs),
              "unread": len(cells) - len(pairs), "kappa": cohen_kappa(pairs),
              "raw_agreement": sum(x == y for x, y in pairs) / len(pairs) if pairs else None,
              "cells": cells}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{run_id}: {report['n']} answers, agreement {report['raw_agreement']:.0%}, "
          f"kappa {report['kappa']:.2f}" if pairs else f"{run_id}: no judged answers found")
    if report["unread"]:
        print(f"{report['unread']} answers the judge could not judge are left out")
    print(f"-> {out}")
    return report


if __name__ == "__main__":
    main()
