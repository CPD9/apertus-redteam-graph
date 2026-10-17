"""Second opinion: re-judge every answer of a run with the independently worded judge and report
how often the two judges agree (Cohen's kappa). Answers come from the run's event log.

    PYTHONPATH=src python -m redteam.rejudge --run RUN_ID
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm as llm_mod
from .judge import second_opinion
from .review import cohen_kappa
from .run import load_hypotheses

RUNS = Path(__file__).resolve().parents[2] / "runs"


def judged_cells(run_id: str) -> list[dict]:
    """Every (prompt, answer, first verdict) the run produced, probe phase and verifier grid."""
    events = [json.loads(l) for l in (RUNS / run_id / "events.jsonl").read_text().splitlines() if l]
    prompts, answers, cells = {}, {}, []
    for e in events:
        hyp, d = e.get("hypothesis"), e.get("data", {})
        if e["node"] == "mutator" and e["status"] == "done":
            prompts[hyp] = d["prompts"]
        elif e["node"] == "target" and e["status"] == "done":
            answers[hyp, d["lang"]] = d["answer"]
        elif e["node"] == "judge" and e["status"] == "done" and (hyp, d["lang"]) in answers:
            cells.append({"hypothesis": hyp, "lang": d["lang"], "prompt": prompts[hyp][d["lang"]],
                          "answer": answers[hyp, d["lang"]], "first": d["violation"]})
        elif e["node"] == "verifier" and e["status"] == "progress" and "answer" in d:
            cells.append({"hypothesis": hyp, "lang": d["lang"], "prompt": d["prompt"],
                          "answer": d["answer"], "first": d["violation"]})
    return cells


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", default=None, help="run id (default: runs/latest)")
    a = ap.parse_args(argv)
    run_id = a.run or (RUNS / "latest").read_text().strip()
    refs = {h["id"]: h for h in load_hypotheses()}
    cells = [c for c in judged_cells(run_id) if c["hypothesis"] in refs]

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
    (RUNS / run_id / "rejudge.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{run_id}: {report['n']} answers, agreement {report['raw_agreement']:.0%}, "
          f"kappa {report['kappa']:.2f}" if pairs else f"{run_id}: no judged answers found")
    return report


if __name__ == "__main__":
    main()
