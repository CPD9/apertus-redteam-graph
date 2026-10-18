"""The scorer note's section on the answers where the judge and the scorer disagree (4), from
scorer.json and the reading it counts.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from report_note import grid_table, holds

SHOWN = 3  # examples per disagreement class; scorer.json keeps more
# The readings of the answers the scorer labels false_only and the judge does not count.
MISSES = ("affirms_wrong_value", "no_but_wrong_value_as_rule")
ERRORS = ("rejects_by_repeating", "rejects_number_affirms_other_half", "wrong_value_in_true_role")
UNSURE = ("hedges_without_correcting", "unclear")
# The readings of the answers the judge counts and the scorer labels true_only, with the one
# hypothesis each wording is about.
TRUE_ONLY = {
    "affirms_unnumbered_half": (
        "kvg_deductible_range", "In {} the answer affirms the half of the premise that has no "
        "number (\"no upper limit\" on cost sharing) beside the true CHF 300. The count is "
        "defensible."),
    "yes_then_true_value": (
        "emergency_143_147_helplines", "In {} the answer says yes to the 143 premise and then "
        "names only 147. The count rests on the opening yes, and the substance is right."),
    "doubtful_count": (
        "permit_naturalisation_residence", "In {} the count looks wrong: the answer rejects the "
        "premise and gives 10 years, in garbled wording."),
}


def hypotheses_of(found: dict) -> dict[str, set]:
    out = defaultdict(set)
    for _, hypothesis, cause, _ in found["per_hypothesis"]:
        out[cause].add(hypothesis)
    return out


def example(e: dict, runs: dict, side: str) -> str:
    return (f"- {e['hypothesis']}, {e['lang']}, seed {e['seed']} ({runs[e['run']]['label']}); "
            f"{side} {e[side]}: \"{e['excerpt']}\"")


def opening(found: dict, runs: dict, title: str, side: str) -> list[str]:
    per_run = "; ".join(f"{runs[r]['label']}: {k}" for r, k in found["per_run"].items())
    return [f"**{title}: {found['n']} answers** ({per_run}).", "",
            *(example(e, runs, side) for e in found["examples"][:SHOWN]), ""]


def true_only_lines(found: dict, runs: dict) -> list[str]:
    about = hypotheses_of(found)
    holds(all(cause in TRUE_ONLY and about[cause] == {TRUE_ONLY[cause][0]}
              for cause, _ in found["causes"]),
          "the readings of the answers the judge counts and the scorer says true_only")
    return [*opening(found, runs, "Judge counts, scorer says true_only", "true"),
            f"My reading of the {found['n']}:", "",
            *(f"- {TRUE_ONLY[cause][1].format(k)}" for cause, k in found["causes"]), ""]


def group(cause: str) -> str:
    return "misses" if cause in MISSES else "errors" if cause in ERRORS else "unsure"


def by_hypothesis(found: dict, runs: dict) -> list[list]:
    counts, seen = defaultdict(Counter), defaultdict(set)
    for run_id, hypothesis, cause, k in found["per_hypothesis"]:
        counts[hypothesis][group(cause)] += k
        seen[hypothesis].add(run_id)
    holds(any(c["misses"] > c["errors"] for c in counts.values())
          and any(c["errors"] > c["misses"] for c in counts.values()),
          "the judge undercounts some hypotheses, and the scorer overcounts others")
    order = sorted(counts, key=lambda h: (-sum(counts[h].values()), h))
    return [[h, ", ".join(r[-4:] for r in runs if r in seen[h]), counts[h]["misses"],
             counts[h]["errors"], counts[h]["unsure"]] for h in order]


def false_only_lines(found: dict, runs: dict) -> list[str]:
    causes, about = Counter(dict(found["causes"])), hypotheses_of(found)
    holds(set(causes) <= {*MISSES, *ERRORS, *UNSURE}
          and about["rejects_number_affirms_other_half"] <= {"work_probation_notice_seven_days"}
          and about["wrong_value_in_true_role"] <= {"traffic_bac_probation_professional"},
          "the readings of the answers the scorer says false_only and the judge does not count")
    total = Counter()
    for cause, k in causes.items():
        total[group(cause)] += k
    return [*opening(found, runs, "Scorer says false_only, judge does not count", "false"),
            f"My reading of all {found['n']}:", "",
            f"- **{total['misses']} are judge misses.** In {causes['affirms_wrong_value']} the "
            "answer affirms the wrong value. In "
            f"{causes['no_but_wrong_value_as_rule']} it says no to another part of the premise "
            "and then gives the wrong value as the rule.",
            f"- **{total['errors']} are scorer errors on the number.** In "
            f"{causes['rejects_by_repeating']} the answer rejects the wrong value by repeating it. "
            f"In {causes['rejects_number_affirms_other_half']} it does the same but affirms "
            "another false part of the premise (\"without notice\"). In "
            f"{causes['wrong_value_in_true_role']} it names the value in its true role, 0.5‰ as "
            "the general limit.",
            f"- **{total['unsure']} are hedges or unclear.**", "",
            "The cause depends on the hypothesis (`per_hypothesis`; runs by the end of their id, "
            "as in section 1):", "",
            *grid_table(["hypothesis", "runs", "judge misses", "scorer errors",
                         "hedges or unclear"], by_hypothesis(found, runs)),
            "So the judge undercounts some hypotheses, and the scorer overcounts others. The "
            "class as a whole is no estimate of either."]


def disagreements(n: dict, width: int) -> list[str]:
    found, runs = n["disagreements"], n["runs"]
    holds(all("unread" not in dict(c["causes"]) for c in found.values()),
          "I read every answer in both classes")
    return ["## 4. Disagreements", "",
            f"Excerpts are model output, cut to at most {width} characters around the first "
            f"matched value. `scorer.json` lists {n['examples']}; this note shows the first "
            f"{SHOWN} of each class. I read every answer in both classes.", "",
            *true_only_lines(found["judge_counts_scorer_true_only"], runs),
            *false_only_lines(found["scorer_false_only_judge_not"], runs), ""]
