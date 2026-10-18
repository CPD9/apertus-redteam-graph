"""CLI: python -m redteam.run [--only ID ...] [--domain voting ...] [--replay] [--promote]"""
from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

from . import llm as llm_mod
from .agents import LANGUAGES
from .graph import Config, run
from .paths import BANKS, ROOT, RUNS

HYPOTHESES = Path(__file__).with_name("hypotheses")


def bank_files(extra: list[str] | None = None) -> list[Path]:
    """The built-in bank files, then those of each extra bank: a file, or a folder of .json files.
    The extra banks default to the paths in REDTEAM_BANKS, separated like PATH and read from
    track_1a/, so every tool that looks hypotheses up by id sees the same banks from any folder."""
    if extra is None:
        extra = [p for p in os.environ.get(BANKS, "").split(os.pathsep) if p]
    banks = [HYPOTHESES, *(ROOT / p for p in extra)]
    return [f for b in banks for f in (sorted(b.glob("*.json")) if b.is_dir() else [b])]


def load_hypotheses(extra: list[str] | None = None) -> list[dict]:
    hyps = []
    for f in bank_files(extra):
        try:
            hyps += json.loads(f.read_text())
        except json.JSONDecodeError as e:
            raise ValueError(f"{f} is not valid JSON: {e}") from None
    # A repeated id would let an extra bank change the reference of a recorded hypothesis.
    if twice := sorted(i for i, n in Counter(h["id"] for h in hyps).items() if n > 1):
        raise ValueError(f"repeated hypothesis ids: {', '.join(twice)}")
    return hyps


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(
        description="Apertus red-team agent graph",
        epilog=f"Hypotheses come from src/redteam/hypotheses/ and the packs named in ${BANKS}, "
               f"e.g. {BANKS}=examples/coding (docs/playbooks/new-domain.md).")
    ap.add_argument("--only", nargs="*", help="hypothesis ids to run (default: all)")
    ap.add_argument("--domain", nargs="*", help="only these domains, e.g. voting permits")
    ap.add_argument("--langs", default="en,de,gsw,fr,it,rm",
                    help="comma-separated, from " + ",".join(LANGUAGES))
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
    langs = a.langs.split(",")
    if unknown := [lang for lang in langs if lang not in LANGUAGES]:
        ap.error(f"unknown language {', '.join(unknown)}; choose from {','.join(LANGUAGES)}")

    try:
        hyps = load_hypotheses()
    except (OSError, ValueError) as e:
        ap.error(str(e))
    # A mistyped name, or one from a pack not loaded, would otherwise just select less, down to
    # an empty run that still replaces runs/latest.
    if unknown := [*sorted(set(a.only or ()) - {h["id"] for h in hyps}),
                   *sorted(set(a.domain or ()) - {h.get("domain") for h in hyps})]:
        ap.error(f"no hypothesis id or domain {', '.join(unknown)} in the banks; "
                 f"name its pack in {BANKS}, e.g. {BANKS}=examples/coding")
    seeds = [h for h in hyps if (not a.only or h["id"] in a.only)
             and (not a.domain or h.get("domain") in a.domain)]
    if a.replay:
        os.environ["REDTEAM_BACKEND"] = "replay"
    llm = llm_mod.detect()
    if llm.backend == "replay" and not (a.only or a.domain):
        # Replay exactly the recorded run, even after new hypotheses were added to the banks.
        recorded = json.loads(llm_mod.MODELS_FILE.read_text()).get("hypotheses")
        seeds = [s for s in seeds if not recorded or s["id"] in recorded]
    print(f"backend={llm.backend} target={llm.model} red={getattr(llm, 'red_model', llm.model)}" + ("   <-- MOCK: results are NOT findings" if llm.backend == "MOCK" else ""))
    cfg = Config(langs=langs, max_attempts=a.attempts, system=a.system,
                 label=a.label, parallel=a.parallel,
                 verify_seeds=[int(x) for x in a.seeds.split(",")], out_dir=RUNS)
    summary = run(llm, seeds, cfg)
    print_results(summary["results"], cfg.min_rate)
    print(f"run_id={summary['run_id']}  events: runs/{summary['run_id']}/events.jsonl")

    if a.promote:
        if llm.backend != "vllm":
            print(f"refusing --promote: {llm.backend} results are not new findings")
        else:
            promote(summary["results"])
    return summary


def promote(results: list[dict]) -> None:
    """Copy the findings files of a run into findings/."""
    for r in results:
        if r.get("path"):  # only reproduced hypotheses have a findings file
            src = ROOT / r["path"]  # logged relative to ROOT, or absolute when outside it
            shutil.copy(src, ROOT / "findings" / src.name)
            print("promoted", src.name)


def shown_status(r: dict) -> str:
    """The graph's status, except that a hypothesis flagged often enough shows as "reproduced"
    when enough of its answers also count and as "below_bar" when not, as on the dashboard."""
    if r["status"] != "finding":
        return r["status"]
    return "reproduced" if r.get("reproduced") else "below_bar"


def print_results(results: list[dict], bar: float) -> None:
    """Status per hypothesis with the share of answers the judge flagged and the share that
    counts (flagged and rated above 0), which decides what is reproduced."""
    print(f"  {'hypothesis':36s} {'status':17s} {'flagged':>7s} {'counted':>7s}")
    for r in results:
        rates = [f"{r[key]:.0%}" if key in r else "" for key in ("overall", "counted")]
        print(f"  {r['id']:36s} {shown_status(r):17s} {rates[0]:>7s} {rates[1]:>7s}".rstrip())
    reproduced = sum(bool(r.get("reproduced")) for r in results)
    print(f"{reproduced} of {len(results)} hypotheses reproduced: counted rate >= {bar:.0%}")


if __name__ == "__main__":
    main()
