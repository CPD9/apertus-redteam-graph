"""The calibration note, docs/audit/calibration.md, from the numbers in calibration.json and the
reading in scorer_reading.json: the judge against the numeric scorer here, speech in
report_calibration_note_speech. The wording is fixed and the numbers come from the data; where a
sentence claims more than its numbers show, holds() stops the note once they no longer bear it out.
"""
from __future__ import annotations

from collections import defaultdict

from report_calibration_note_rates import corrected
from report_calibration_note_speech import speech
from report_calibration_speech import ALL
from report_note import grid_table, holds, listed, ratio, span, two

from redteam.numbers_in_text import LANGS

SCORER_ERRORS = ("rejects_by_repeating", "rejects_number_affirms_other_half",
                 "wrong_value_in_true_role")
SKIPPED = ("kvg_switch_deadline", "hist_womens_suffrage_1971")


def accuracy(run: dict) -> dict:
    return run["reference"]["accuracy"]


def header(n: dict) -> list[str]:
    runs = list(n["runs"].values())
    spec = [accuracy(r)[ALL]["specificity"] for r in runs]
    holds(all(h not in r["per_hypothesis"] for r in runs for h in SKIPPED),
          "neither skipped hypothesis is in the reference")
    leaves, unlabelled = [], []  # the first run in full, the others short
    for i, r in enumerate(runs):
        x, both = r["reference"], r["scored_by_label"]["both"]
        scored, other = sum(r["scored_by_label"].values()), x["labelled"] - x["asserts"]
        if i == 0:
            leaves.append(f"{x['labelled']} labelled answers on the {r['label']} ({x['asserts']} "
                          f"false_only, {other} true_only, {x['hypotheses']} hypotheses)")
            unlabelled.append(f"{both} of the {scored} scored answers on the {r['label']}")
        else:
            leaves.append(f"{x['labelled']} on the {r['label']} ({x['asserts']} and {other}, "
                          f"{x['hypotheses']} hypotheses)")
            unlabelled.append(f"{both} of {scored} on the {r['label']}")
    named = " and ".join(f"{r['label']} `{run_id}`" for run_id, r in n["runs"].items())
    judges = listed(sorted({r["judge"] for r in runs}))
    return ["# Judge calibration", "",
            f"Written by `{n['script']}` (`cd track_1a && python3 {n['script']}`) together with "
            "`calibration.json`, which holds every number here except the reading of answers in "
            f"section 1, from `scorer_reading.json`. Runs: {named}, both judged by {judges}, and "
            f"speech `{n['speech']['run']}`. The judge counts an answer by `Answer.confirmed` "
            "(flagged and severity above 0). Every analysis here was chosen after the runs were "
            "read, so all of it is post hoc. Nothing here is a human label. A value whose third "
            "decimal is a final 5 keeps it, since the JSON has rounded it once already.", "",
            f"**Reference.** The numeric scorer (`{n['scorer']}`, "
            "`src/redteam/numeric_facts.json`) is used only where its label is decisive: "
            "false_only means the answer asserts the error, true_only that it does not. That "
            f"leaves {listed(leaves)}. The facts table skips {SKIPPED[0]} (a date) and "
            f"{SKIPPED[1]} (1971 is on both sides), so neither is in the reference.", "",
            "Limits:", "",
            "- **The scorer is a second imperfect instrument.** It ignores negation, and a "
            "true_only answer can still affirm the part of the premise that has no number.",
            "- **Coverage is narrow.** Only numeric hypotheses are covered, and Sp rests on "
            f"{listed(s['n'] for s in spec)} answers from {listed(s['hypotheses'] for s in spec)} "
            "hypotheses.",
            "- **Agreement is not truth.** Se and Sp measure agreement with the scorer, not "
            "accuracy.",
            f"- **The \"both\" answers have no label.** {listed(unlabelled)} state the wrong and "
            "the right value. That is where refutations that repeat the wrong number sit, so "
            "their Se and Sp may well differ from the decisive answers'.", ""]


def accuracy_rows(columns: list[dict]) -> list[list]:
    rows = []
    for side, name in (("sensitivity", "Se"), ("specificity", "Sp")):
        cells = [c[side] for c in columns]
        rows += [[name, *(f"{two(c['rate'])} ({ratio(c)})" for c in cells)],
                 ["resampling hypotheses", *(span(c["cluster_ci95"]) for c in cells)],
                 ["Wilson", *(span(c["ci95"]) for c in cells)],
                 [f"hypotheses behind {name}", *(c["hypotheses"] for c in cells)]]
    return [*rows, ["Se + Sp − 1", *(two(c["youden"]) for c in columns)]]


def scorer_errors(reading: dict, run_id: str) -> tuple[int, str]:
    """How many answers of a run are read as scorer errors, and which: "h en/11, de/22"."""
    found = defaultdict(list)
    for (run, hypothesis, lang, seed), row in sorted(
            reading.items(), key=lambda item: (LANGS.index(item[0][2]), item[0][3])):
        if run == run_id and row.get("cause") in SCORER_ERRORS:
            found[hypothesis].append(f"{lang}/{seed}")
    named = "; ".join(f"{h} {', '.join(cases)}" for h, cases in sorted(found.items()))
    return sum(map(len, found.values())), named


def misses_lines(n: dict, reading: dict) -> list[str]:
    runs, unsure = n["runs"], n["unsure"][0]
    left, flagged, carriers, errors, rates = [], [], [], [], []
    for run_id, x in runs.items():
        missed, asserting = x["misses"], accuracy(x)[ALL]["sensitivity"]["n"]
        left.append(f"{missed['n']} of {asserting} ({x['label']})")
        flagged.append((missed["not_flagged"], missed["flagged_without_severity"]))
        (a, h1), (b, h2) = sorted(((c["fn"], h) for h, c in x["per_hypothesis"].items()),
                                  reverse=True)[:2]
        holds(a + b > missed["n"] / 2, "a few hypotheses carry the misses")
        carriers.append(f"On the {x['label']}, {h1} ({a}) and {h2} ({b}) give {a + b} of the "
                        f"{missed['n']}")
        count, named = scorer_errors(reading, run_id)
        holds(count > 0, "some false_only answers reject the wrong value or name it in its role")
        errors.append(f"{count} of the {missed['n']} on the {x['label']} ({named})")
        rates.append(f"{missed['n']}/{asserting}")
    fp = {x["label"]: (x["per_hypothesis"].get(unsure, {}).get("fp", 0),
                       sum(c["fp"] for c in x["per_hypothesis"].values())) for x in runs.values()}
    label = max(fp, key=lambda k: fp[k][0])
    holds(fp[label][0] > fp[label][1] / 2, f"{unsure} gives most of the false positives")
    sp_cells = [t["specificity"]["n"] for x in runs.values()
                for t in accuracy(x)["per_lang"].values()]
    return [f"- **What is left out.** `Answer.confirmed` leaves out {listed(left)} false_only "
            f"answers. The judge did not flag {listed(f for f, _ in flagged)} of them. It flagged "
            f"the other {listed(s for _, s in flagged)} with severity 0, which the counting rule "
            "drops.",
            f"- **A few hypotheses carry the misses.** {'. '.join(carriers)} (`per_hypothesis` in "
            "the JSON).",
            "- **Scorer errors push both Se and Sp down.** Reading the excerpts, some false_only "
            "answers reject the wrong value or name it in its true role. That covers at least "
            f"{listed(errors)}. This is a reading of model output for this audit, not a label. "
            "Such answers bias Se low, just as true_only answers that affirm the other half of the "
            f"premise bias Sp low ({unsure} gives {fp[label][0]} of the {fp[label][1]} false "
            f"positives on the {label}). So neither {' nor '.join(rates)} is a judge miss rate.",
            f"- **Per-language Sp cannot be read.** Each cell has {min(sp_cells)} to "
            f"{max(sp_cells)} answers.", ""]


def section_one(n: dict, reading: dict) -> list[str]:
    runs = n["runs"]
    columns = [accuracy(x)[ALL] for x in runs.values()] + [n["both_runs_accuracy"][ALL]]
    per_lang = [[x["label"], *(f"{ratio(t['sensitivity'])} · {ratio(t['specificity'])}"
                               for t in accuracy(x)["per_lang"].values())]
                for x in runs.values()]
    return ["## 1. Sensitivity and specificity", "",
            "Answers cluster by hypothesis, so the interval to read resamples hypotheses "
            f"({n['bootstrap']['draws']} draws, seed {n['bootstrap']['seed']}). The Wilson "
            "interval treats answers as independent and is too narrow. In \"both runs\" a "
            "hypothesis pools its answers from both runs, so the shared hypotheses are drawn "
            "once.", "",
            *grid_table(["", *(x["label"] for x in runs.values()), "both runs"],
                        accuracy_rows(columns)),
            "Per language, Se · Sp as k/n:", "",
            *grid_table(["", *LANGS], per_lang), *misses_lines(n, reading)]


def markdown(n: dict, reading: dict) -> str:
    """The note from calibration.json's numbers and the reading rows, keyed as report_scorer's
    load_reading keys them."""
    return "\n".join([*header(n), *section_one(n, reading), *corrected(n), *speech(n["speech"])])
