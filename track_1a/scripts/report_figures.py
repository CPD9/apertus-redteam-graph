"""Figures for the technical report, drawn as plain SVG from recorded runs.

    python3 scripts/report_figures.py --canonical RUN [--target70 RUN] [--mitigation RUN]
        [--speech SPEECH_RUN] [--bank2 RUN] [--out docs/figures]

A run is an id, looked up in runs/ and then in data/runs/, or a folder. SPEECH_RUN is a speech run
folder (report_speech says which files it reads). Every number a figure shows is also written to
numbers.json, so the report text quotes exactly what the figures show. The run given as --bank2
gets no figure, only its hypotheses counted one by one in numbers.json. The report's figures:

    python3 scripts/report_figures.py --canonical 20261016-172309-1f71 \
        --target70 20261017-140533-a21a --mitigation 20261017-144423-5519 \
        --speech data/runs/speech/20261017-141121 --bank2 20261017-143329-b04d
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # without pip install -e

from report_charts import BLUE, RED, bar_chart, count_label, heatmap, signed_points  # noqa: E402
from report_compare import languages_by_size, mitigation  # noqa: E402
from report_runs import Skip, control_shares, hypothesis_counts, recorded, title  # noqa: E402
from report_speech import speech_dialects  # noqa: E402

from redteam.agents import LANG_NAMES  # noqa: E402
from redteam.graph import Config  # noqa: E402
from redteam.group import THEMES, subject  # noqa: E402
from redteam.paths import ROOT  # noqa: E402


def rounded(values):
    return [round(v, 4) for v in values]


def control_caveat(hypothesis):
    """Why the neutral questions of the hypothesis's finding differ from its premise questions,
    as themes.json words it; None when they do not."""
    return next((t for t in THEMES if subject(t, hypothesis)), {}).get("control_caveat")


def gap_heatmap(rec):
    rows = []
    for hyp, ver in rec.verified.items():
        cells = {lang: ver["per_lang"][lang] for lang in rec.run.langs}
        rates = [c["rate"] for c in cells.values()]
        rows.append({"id": hyp, "label": title(hyp),
                     "reproduced": ver["overall"] >= Config.min_rate,
                     "gap": round(max(rates) - min(rates), 4), "overall": round(ver["overall"], 4),
                     "per_lang": {lang: {"k": c["k"], "n": c["n"], "rate": round(c["rate"], 4)}
                                  for lang, c in cells.items()}})
    if not rows:
        raise Skip(f"run {rec.id} has no verified hypotheses")
    rows.sort(key=lambda r: (-r["gap"], -r["overall"], r["id"]))
    sizes = sorted({c["n"] for r in rows for c in r["per_lang"].values()})
    note = (f"{count_label(sizes, 'answers per cell')}, so one answer can move a rate by "
            f"{100 / sizes[0]:.0f} points and close gaps can swap places.")
    if not all(r["reproduced"] for r in rows):
        note = (f"Grey labels: under {Config.min_rate:.0%} of answers wrong, so not reproduced. "
                f"{note}")
    heading = (f"Share of wrong answers of {rec.name} per hypothesis and language, sorted by "
               "the gap between the most and the least affected language")
    svg = heatmap(rows, {lang: LANG_NAMES[lang] for lang in rec.run.langs}, note, heading)
    return svg, {"run": rec.id, "model": rec.run.model, "langs": rec.run.langs,
                 "answers_per_cell": sizes, "bar": Config.min_rate,
                 "uncounted": sorted(rec.uncounted), "rows": rows}


def premise_vs_neutral(rec):
    path = rec.dir / "control.json"
    controls = json.loads(path.read_text()) if path.exists() else []
    if not controls:
        raise Skip(f"run {rec.id} has no control results")
    shares = control_shares(rec, controls)
    # Left out of their finding after reading the answers; themes.json gives the reasons.
    left_out = sorted({h for t in THEMES for h in t.get("excluded", {})} & set(shares))
    # Reproduced hypotheses only: still over the bar when answers correcting the premise do not
    # count, and not left out of their finding after reading.
    table = sorted(({"id": h, "label": title(h), "control_caveat": control_caveat(h),
                     "premise_rate": round(p.rate, 4), "premise_ci95": rounded(p.ci95),
                     "premise_n": p.n, "neutral_rate": round(n.rate, 4),
                     "neutral_ci95": rounded(n.ci95), "neutral_n": n.n,
                     "gap": round(p.rate - n.rate, 4)}
                    for h, (p, n) in shares.items()
                    if p.rate >= Config.min_rate and h not in left_out),
                   key=lambda r: (-r["gap"], r["id"]))
    if not table:
        raise Skip(f"no hypothesis of run {rec.id} with a control is reproduced")
    rows = [(r["label"] + (" †" if r["control_caveat"] else ""),
             [{"rate": r["premise_rate"], "ci95": r["premise_ci95"]},
              {"rate": r["neutral_rate"], "ci95": r["neutral_ci95"]}],
             signed_points(r["gap"])) for r in table]
    sizes = [r[key] for r in table for key in ("premise_n", "neutral_n")]
    note = ("Share of answers that state the error, 95% Wilson CI; gap in percentage points, "
            + count_label(sizes, "answers per hypothesis and condition") + ".")
    if any(r["control_caveat"] for r in table):
        note += (" † Its finding notes that some of its neutral questions ask something other "
                 "than the premise questions.")
    if left_out:
        note += (" Left out after reading the answers: "
                 + ", ".join(title(h) for h in left_out) + ".")
    svg = bar_chart(rows, [("With the false premise", RED), ("Asked neutrally", BLUE)], note,
                    f"Premise versus neutral question, {len(rows)} reproduced hypotheses of "
                    f"{rec.name}", right_header="gap")
    return svg, {"run": rec.id, "excluded": left_out, "rows": table}


def need(value, flag):
    if value is None:
        raise Skip(f"no {flag} given")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description="Draw the report figures from recorded runs.")
    ap.add_argument("--canonical", required=True, help="run id (or folder) of the main run")
    ap.add_argument("--target70", help="run with Apertus 70B as target")
    ap.add_argument("--mitigation", help="run with the mitigation system prompt")
    ap.add_argument("--speech", type=Path, help="folder of a speech run")
    ap.add_argument("--bank2",
                    help="run whose hypotheses are counted one by one, without a figure")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "figures")
    a = ap.parse_args(argv)
    canonical = recorded(a.canonical)
    target70 = recorded(a.target70) if a.target70 else None
    mitigated = recorded(a.mitigation) if a.mitigation else None
    bank2 = hypothesis_counts(a.bank2) if a.bank2 else None
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
    if bank2:
        numbers["bank2"] = bank2
    (a.out / "numbers.json").write_text(json.dumps(numbers, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {a.out / 'numbers.json'}")


if __name__ == "__main__":
    main()
