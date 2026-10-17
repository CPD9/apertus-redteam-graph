"""CLI: python -m redteam.run [--only ID ...] [--domain voting ...] [--replay] [--promote]"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from . import llm as llm_mod
from .graph import Config, run

ROOT = Path(__file__).resolve().parents[2]
HYPOTHESES = Path(__file__).with_name("hypotheses")


def load_hypotheses() -> list[dict]:
    return [h for f in sorted(HYPOTHESES.glob("*.json")) for h in json.loads(f.read_text())]


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description="Apertus red-team agent graph")
    ap.add_argument("--only", nargs="*", help="hypothesis ids to run (default: all)")
    ap.add_argument("--domain", nargs="*", help="only these domains, e.g. voting permits")
    ap.add_argument("--langs", default="en,de,gsw,fr,it,rm")
    ap.add_argument("--attempts", type=int, default=4)
    ap.add_argument("--seeds", default="11,22,33")
    ap.add_argument("--system", help="system prompt for the target (mitigation experiments)")
    ap.add_argument("--label", default="", help="tag stored with the run, e.g. '70B target'")
    ap.add_argument("--parallel", type=int, default=6, help="hypotheses in flight at once")
    ap.add_argument("--replay", action="store_true",
                    help="answer every LLM call from data/llm_cache (no GPU needed)")
    ap.add_argument("--promote", action="store_true",
                    help="copy findings into findings/ (refused for MOCK runs)")
    a = ap.parse_args(argv)

    seeds = load_hypotheses()
    if a.only:
        seeds = [s for s in seeds if s["id"] in a.only]
    if a.domain:
        seeds = [s for s in seeds if s.get("domain") in a.domain]
    if a.replay:
        os.environ["REDTEAM_BACKEND"] = "replay"
    llm = llm_mod.detect()
    if llm.backend == "replay" and not (a.only or a.domain):
        # Replay exactly the recorded run, even after new hypotheses were added to the banks.
        recorded = json.loads(llm_mod.MODELS_FILE.read_text()).get("hypotheses")
        seeds = [s for s in seeds if not recorded or s["id"] in recorded]
    print(f"backend={llm.backend} target={llm.model} red={getattr(llm, 'red_model', llm.model)}" + ("   <-- MOCK: results are NOT findings" if llm.backend == "MOCK" else ""))
    cfg = Config(langs=a.langs.split(","), max_attempts=a.attempts, system=a.system,
                 label=a.label, parallel=a.parallel,
                 verify_seeds=[int(x) for x in a.seeds.split(",")], out_dir=ROOT / "runs")
    summary = run(llm, seeds, cfg)
    for r in summary["results"]:
        print(f"  {r['id']:28s} {r['status']:18s} {r.get('overall', '')}")
    print(f"run_id={summary['run_id']}  events: runs/{summary['run_id']}/events.jsonl")

    if a.promote:
        if llm.backend != "vllm":
            print(f"refusing --promote: {llm.backend} results are not new findings")
        else:
            for r in summary["results"]:
                if r["status"] == "finding":
                    shutil.copy(r["path"], ROOT / "findings" / Path(r["path"]).name)
                    print("promoted", Path(r["path"]).name)
    return summary


if __name__ == "__main__":
    main()
