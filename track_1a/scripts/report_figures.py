"""Figures for the technical report, drawn as plain SVG from recorded runs.

    python3 scripts/report_figures.py --canonical RUN [--target70 RUN] [--mitigation RUN]
        [--speech runs/speech/STAMP/results.json] [--out docs/figures]

Every number a figure shows is also written to numbers.json, so the report text quotes exactly
what the figures show. The report's figures:

    python3 scripts/report_figures.py --canonical 20261016-172309-1f71 \
        --target70 20261017-140533-a21a --mitigation 20261017-144423-5519 \
        --speech runs/speech/20261017-141121/results.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NamedTuple

from report_charts import (BLUE, RED, SIZE_COLORS, bar_chart, count_label, heatmap,
                           signed_points)
from report_runs import Run, comparison, control_shares, load_run, readable, same_model

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redteam.agents import LANG_NAMES  # noqa: E402
from redteam.graph import Config  # noqa: E402

DIALECTS = {"ag": "Aargau", "be": "Bern", "bs": "Basel", "gr": "Graubünden", "lu": "Lucerne",
            "sg": "St. Gallen", "vs": "Valais", "zh": "Zurich"}


class Skip(Exception):
    """A figure whose inputs are missing; main() reports it in one line."""


class Arm(NamedTuple):
    run: Run
    name: str
    color: str
    where: str  # completes "never broken ...", e.g. "with the prompt"


def rounded(values):
    return [round(v, 4) for v in values]


def gap_heatmap(run):
    rows = []
    for hyp, ver in run.verified.items():
        cells = {lang: ver["per_lang"][lang] for lang in run.langs}
        rates = [c["rate"] for c in cells.values()]
        rows.append({"id": hyp, "finding": ver["overall"] >= Config.min_rate,
                     "gap": round(max(rates) - min(rates), 4), "overall": round(ver["overall"], 4),
                     "per_lang": {lang: {"k": c["k"], "n": c["n"], "rate": round(c["rate"], 4)}
                                  for lang, c in cells.items()}})
    if not rows:
        raise Skip(f"run {run.id} has no verified hypotheses")
    rows.sort(key=lambda r: (-r["gap"], -r["overall"], r["id"]))
    sizes = sorted({c["n"] for r in rows for c in r["per_lang"].values()})
    note = (f"{count_label(sizes, 'answers per cell')}, so one answer can move a rate by "
            f"{100 / sizes[0]:.0f} points and close gaps can swap places.")
    if not all(r["finding"] for r in rows):
        note = (f"Grey labels: violated in under {Config.min_rate:.0%} of answers, so not a "
                f"finding. {note}")
    title = (f"Violation rate of {run.name} per hypothesis and language, sorted by the gap "
             "between the most and the least affected language")
    svg = heatmap(rows, {lang: LANG_NAMES[lang] for lang in run.langs}, note, title)
    return svg, {"run": run.id, "model": run.model, "langs": run.langs, "answers_per_cell": sizes,
                 "finding_threshold": Config.min_rate, "rows": rows}


def premise_vs_neutral(run):
    path = run.dir / "control.json"
    controls = json.loads(path.read_text()) if path.exists() else []
    if not controls:
        raise Skip(f"run {run.id} has no control results")
    shares = control_shares(run, controls)
    # Only hypotheses that are still findings when answers correcting the premise do not count.
    table = sorted(({"id": h, "label": readable(h), "premise_rate": round(p.rate, 4),
                     "premise_ci95": rounded(p.ci95), "premise_n": p.n,
                     "neutral_rate": round(n.rate, 4), "neutral_ci95": rounded(n.ci95),
                     "neutral_n": n.n, "gap": round(p.rate - n.rate, 4)}
                    for h, (p, n) in shares.items() if p.rate >= Config.min_rate),
                   key=lambda r: (-r["gap"], r["id"]))
    rows = [(r["label"], [{"rate": r["premise_rate"], "ci95": r["premise_ci95"]},
                          {"rate": r["neutral_rate"], "ci95": r["neutral_ci95"]}],
             signed_points(r["gap"])) for r in table]
    sizes = [r[key] for r in table for key in ("premise_n", "neutral_n")]
    svg = bar_chart(rows, [("With the false premise", RED), ("Asked neutrally", BLUE)],
                    "Share of answers that assert the error, 95% Wilson CI; gap in percentage "
                    "points, " + count_label(sizes, "answers per finding and condition"),
                    f"Premise versus neutral question, {len(rows)} hypotheses of {run.name}",
                    right_header="gap")
    return svg, {"run": run.id, "rows": table}


def judge_sentence(runs):
    judges = sorted({run.judge for run in runs} - {None})
    if len(judges) != 1:
        return f" Judges: {', '.join(judges)}." if judges else ""
    own = [run.name for run in runs if same_model(judges[0], run.model)]
    return f" Judge: {judges[0]}" + (f", so {own[0]} judged its own answers." if own else ".")


def compare_note(arms, numbers):
    unbroken = [f"{len(numbers['never_broken'][arm.name])} {arm.where}" for arm in arms
                if numbers["never_broken"][arm.name]]
    note = (f"Violating answers over the {len(numbers['hypotheses'])} hypotheses attacked in "
            "both runs; 95% CI from resampling hypotheses.")
    if unbroken:
        note += (f" Never broken, so 0 of {numbers['answers_per_language']} answers per "
                 f"language: {' and '.join(unbroken)}.")
    note += (f" Each run attacked adaptively, and {numbers['same_prompts']} of the "
             f"{numbers['verified_in_both']} hypotheses verified in both used the same prompts.")
    if numbers["failed"]:
        note += f" Left out after an error: {', '.join(numbers['failed'])}."
    return note + judge_sentence([arm.run for arm in arms])


def compare(before, after, title):
    numbers = comparison(before.run, after.run, [before.name, after.name])
    if numbers is None:
        raise Skip(f"runs {before.run.id} and {after.run.id} have no verified hypothesis that "
                   "both finished")
    rows = [(LANG_NAMES.get(key, "All languages"), list(entries.values()), None)
            for key, entries in numbers["per_lang"].items()]
    svg = bar_chart(rows, [(before.name, before.color), (after.name, after.color)],
                    compare_note((before, after), numbers), title, total=True)
    return svg, numbers


def languages_by_size(small, large):
    return compare(Arm(small, small.name, SIZE_COLORS[0], f"on {small.name}"),
                   Arm(large, large.name, SIZE_COLORS[1], f"on {large.name}"),
                   f"Violation rate per language, {small.name} versus {large.name}")


def mitigation(mitigated, baselines):
    before = next((run for run in baselines
                   if run and run.model == mitigated.model and not run.system), None)
    if before is None:
        raise Skip(f"no run of {mitigated.model} without a system prompt to compare against")
    svg, numbers = compare(Arm(before, "No system prompt", RED, "without the prompt"),
                           Arm(mitigated, "Mitigation system prompt", BLUE, "with the prompt"),
                           "Violation rate per language before and after the mitigation system "
                           f"prompt, {before.name}")
    return svg, numbers | {"system_prompt": mitigated.system}


def speech_dialects(path):
    results = json.loads(path.read_text())
    judged = sorted((d for d in results["dialects"] if "unrelated_rate" in d),
                    key=lambda d: (-d["unrelated_rate"], d["dialect"]))
    if not judged:
        raise Skip(f"no dialect in {path} has a judged meaning (speech_eval --judge)")
    verdicts = ("same", "partial", "unrelated")
    table = [{"dialect": d["dialect"], "name": DIALECTS.get(d["dialect"], d["dialect"]),
              "unrelated": d["unrelated"], "rate": round(d["unrelated_rate"], 4),
              "ci95": d["unrelated_ci95"],
              "n": sum(c["dialect"] == d["dialect"] and c.get("meaning") in verdicts
                       for c in results["clips"])} for d in judged]
    model, judge = results["model"].rsplit("/", 1)[-1], results["judge"]
    own = ", the model that translated" if same_model(judge, results["model"]) else ""
    svg = bar_chart([(f"{r['name']} ({r['dialect'].upper()})", [r], None) for r in table],
                    [("Translation unrelated to what was said", RED)],
                    f"Share of judged translations with 95% Wilson CI, "
                    f"{count_label([r['n'] for r in table], 'clips per dialect')}. Translated by "
                    f"{model}, judged by {judge}{own}.",
                    f"Unrelated translations of Swiss German speech per dialect, {model}")
    return svg, {"results": str(path), "model": results["model"], "judge": judge, "rows": table}


def need(value, flag):
    if value is None:
        raise Skip(f"no {flag} given")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draw the report figures from recorded runs.")
    ap.add_argument("--canonical", required=True, help="run id (or directory) of the main run")
    ap.add_argument("--target70", help="run with Apertus 70B as target")
    ap.add_argument("--mitigation", help="run with the mitigation system prompt")
    ap.add_argument("--speech", type=Path, help="runs/speech/<stamp>/results.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "figures")
    a = ap.parse_args(argv)
    canonical = load_run(a.canonical)
    target70 = load_run(a.target70) if a.target70 else None
    mitigated = load_run(a.mitigation) if a.mitigation else None
    plan = {
        "gap_heatmap": lambda: gap_heatmap(canonical),
        "premise_vs_neutral": lambda: premise_vs_neutral(canonical),
        "languages_8b_70b": lambda: languages_by_size(canonical, need(target70, "--target70")),
        "mitigation": lambda: mitigation(need(mitigated, "--mitigation"), [target70, canonical]),
        "speech_dialects": lambda: speech_dialects(need(a.speech, "--speech")),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    numbers = {"canonical_run": canonical.id}
    for name, draw in plan.items():
        path = a.out / f"{name}.svg"
        try:
            svg, numbers[name] = draw()
        except Skip as reason:
            path.unlink(missing_ok=True)  # an older figure would contradict numbers.json
            print(f"skip {path.name}: {reason}")
            continue
        path.write_text(svg)
        print(f"wrote {path}")
    (a.out / "numbers.json").write_text(json.dumps(numbers, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {a.out / 'numbers.json'}")


if __name__ == "__main__":
    main()
