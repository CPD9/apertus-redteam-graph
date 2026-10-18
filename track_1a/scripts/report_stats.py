"""How strongly the recorded runs support the report's language, mitigation and model-size effects,
with tests that respect how answers are nested: each hypothesis is asked in six languages with three
seeds, and the three answers to one prompt are not three independent users. Answers count as the
findings count them (Answer.confirmed). Writes docs/audit/stats.json and docs/audit/stats.md.

    cd track_1a && PYTHONPATH=src python3 scripts/report_stats.py
"""
from __future__ import annotations

import json
import re
from collections import Counter
from math import isfinite
from pathlib import Path

from redteam import answers, paths, significance as sig
from redteam.cache import CACHE_DIR
from redteam.graph import Config
from redteam.run import load_hypotheses

TRACK = Path(__file__).resolve().parents[1]
OUT, REPORT = TRACK / "docs" / "audit", TRACK / "technical_report.md"
SMALL, LARGE, MITIGATED = "20261016-172309-1f71", "20261017-140533-a21a", "20261017-144423-5519"
HYPOTHESES = {h["id"]: h for h in load_hypotheses()}
FINISHED = {"finding", "not_reproducible"}  # the verifier logged every answer of the hypothesis
ALPHA = 0.05
# Per-hypothesis splits that rest on verdicts the report or the answers put in doubt: a reading
# written by hand, by run and hypothesis.
DOUBTS = {
    (SMALL, "vote_initiative_signatures"):
        "one of the 15 non-English answers counted (rm, seed 22, severity 8) only repeats the "
        "question, as the report says; at 14 of 15 Fisher gives p 4/816 = 0.0049",
    (LARGE, "vote_mandatory_referendum"):
        "all three English answers open with \"Yes, that is true\" or \"Yes, that is correct\" in "
        "reply to the premise question, yet the judge scored them not flagged, severity 0, while "
        "it counted the answers of the other five languages",
}


def p3(x):
    """Counts as they are, others to three significant digits; None for an odds ratio with nothing
    on one side."""
    if isinstance(x, int):
        return x
    return float(f"{x:.3g}") if isfinite(x) else None


def grid(answer_list):
    """Counted answers (1 or 0) by hypothesis, then language, in seed order."""
    out = {}
    for a in answer_list:
        out.setdefault(a.hypothesis, {}).setdefault(a.lang, []).append(int(a.confirmed))
    return out


def rate(ys):
    return sum(ys) / len(ys)


def counted(by_lang):
    """A hypothesis's counted answers over all its languages."""
    return sum(map(sum, by_lang.values()))


def units(by_lang):
    return [(lang, (sum(ys), len(ys))) for lang, ys in by_lang.items()]


def cells(g):
    return [units(by_lang) for by_lang in g.values()]


def singles(g):
    return [[(lang, (y, 1)) for lang, ys in by_lang.items() for y in ys] for by_lang in g.values()]


def table(ys, other):
    return sum(ys), len(ys) - sum(ys), sum(other), len(other) - sum(other)


def pair(first, second):
    """Two numbers as a stratum of sig.paired_shift."""
    return [("first", first), ("second", second)]


def permuted(strata, statistic, draws):
    test = sig.permutation_test(strata, statistic, draws)
    return {"observed": p3(test.observed), "expected": p3(test.expected), "p": p3(test.p)}


def paired(test, first="higher", second="lower"):
    return {first: test.first, second: test.second, "p": p3(test.p)}


def adjusted(rows, pvalues):
    """Each row with its p and that p Holm-adjusted over all of them."""
    return [row | {"p": p3(p), "p_holm": p3(h)}
            for row, p, h in zip(rows, pvalues, sig.holm(pvalues))]


def holm_paired(tests, first="higher", second="lower"):
    tests = list(tests)
    return adjusted([{first: t.first, second: t.second} for t in tests], [t.p for t in tests])


def coverage(run):
    """How many hypotheses enter the tests, and the outcome of each one left out for want of
    verified answers."""
    entered = {a.hypothesis for a in run.answers}
    return {"hypotheses": len(entered), "left_out": {h: run.outcome.get(h, "unknown")
                                                     for h in run.hypotheses if h not in entered}}


def language_effect(g, draws):
    """Variance of the pooled language rates, against shuffling whole prompt cells, or single
    answers, between the languages of each hypothesis."""
    totals = sig.label_totals([unit for stratum in cells(g) for unit in stratum])
    return {"rates": {lang: round(k / n, 4) for lang, (k, n) in totals.items()},
            "cells_shuffled": permuted(cells(g), sig.rate_variance, draws),
            "answers_shuffled": permuted(singles(g), sig.rate_variance, draws)}


def english_vs(g):
    """Each language against English: CMH over hypotheses, and the sign test of the per-hypothesis
    difference, each Holm-adjusted over the five languages."""
    others = [lang for lang in next(iter(g.values())) if lang != "en"]
    tests = [sig.cmh([table(c[lang], c["en"]) for c in g.values()]) for lang in others]
    rows = adjusted([{"odds_ratio": p3(t.odds_ratio)} for t in tests], [t.p for t in tests])
    signs = holm_paired(sig.sign_test([sum(c[lang]) - sum(c["en"]) for c in g.values()])
                        for lang in others)
    return {lang: row | {"sign": sign} for lang, row, sign in zip(others, rows, signs)}


def different_truths(g, draws):
    """Hypotheses with one language at all answers counted and another at none, against shuffling
    the language labels of single answers within each hypothesis. Shuffling whole cells leaves the
    count as it is, so there is no null that keeps a prompt's answers together."""
    return {"hypotheses": len(g), **permuted(singles(g), sig.split_strata, draws)}


def is_split(by_lang):
    return sig.split_strata([units(by_lang)]) == 1


def control_truths(run, rows, neutral, draws):
    """different_truths of the neutral control beside the premise answers of the same hypotheses,
    and McNemar of the hypotheses split under one condition only. control.json keeps per-language
    rates of raw flags only, so neutral holds its answers replayed from the cache; the last entry
    counts the logged rates that equal the replayed flags."""
    flags = {}
    for a in neutral:
        flags.setdefault((a.hypothesis, a.lang), []).append(a.flagged)
    logged = [abs(value - rate(flags[r["id"], lang])) < 1e-9
              for r in rows for lang, value in r.get("neutral_by_lang", {}).items()]
    asked = grid(neutral)
    premise = grid(a for a in run.answers if a.hypothesis in asked)
    splits = [(is_split(premise[h]), is_split(asked[h])) for h in premise]
    return {"premise_same_hypotheses": different_truths(premise, draws),
            "neutral": different_truths(asked, draws),
            "split_in_one_only": paired(sig.mcnemar(splits), "premise", "neutral"),
            "logged_rates_equal_raw_flags": [sum(logged), len(logged)]}


def per_hypothesis(g):
    """English against the other languages within each hypothesis by Fisher's exact test of one
    2x2 table: Holm over all hypotheses, and Bonferroni over Tarone's family of the hypotheses whose
    margins can reach significance. English is one prompt there and the others five, so seeds are
    the only replication; with whole cells shuffled no hypothesis could get below 1/6."""
    tables = {h: table(c["en"], [y for lang, ys in c.items() if lang != "en" for y in ys])
              for h, c in g.items()}
    p = {h: sig.fisher(*t) for h, t in tables.items()}
    holm = dict(zip(p, sig.holm(list(p.values()))))
    family = sig.tarone([sig.fisher_floor(a + b, c + d, a + c) for a, b, c, d in tables.values()],
                        ALPHA)
    a, b, c, d = next(iter(tables.values()))
    floor = sig.fisher(0, a + b, c + d, 0)
    below = [{"hypothesis": h, "english": f"{t[0]}/{t[0] + t[1]}",
              "others": f"{t[2]}/{t[2] + t[3]}", "p": p3(p[h]), "p_holm": p3(holm[h]),
              "p_tarone": p3(min(1.0, p[h] * family))}
             for h, t in sorted(tables.items(), key=lambda item: p[item[0]]) if p[h] < ALPHA]
    return {"test": "Fisher's exact test, two-sided", "hypotheses": len(p), "below_alpha": below,
            "holm_below_alpha": [h for h in p if holm[h] < ALPHA], "tarone_family": family,
            "tarone_below_alpha": [h for h in p if p[h] * family < ALPHA],
            "floor_p": p3(floor), "floor_p_holm": p3(min(1.0, floor * len(p))),
            "cell_floor_p": p3(1 / len(next(iter(g.values()))))}


def detectable(g, power_draws):
    """The odds ratio against English that the tests find with 80% power at alpha 0.05, within one
    hypothesis and for one language pooled over hypotheses, with the pooled rate it implies (the
    mean over simulated hypotheses) and the rate of a hypothesis at the English mean."""
    english = [y for c in g.values() for y in c["en"]]
    base, seeds, others = rate(english), len(english) // len(g), len(next(iter(g.values()))) - 1
    rho = sig.icc([[y for ys in c.values() for y in ys] for c in g.values()])
    out = {"english_rate": p3(base), "icc_hypothesis": p3(rho),
           "icc_cell": p3(sig.icc([ys for c in g.values() for ys in c.values()]))}
    designs = {"one_hypothesis": sig.Design(1, (seeds, seeds * others), 0.0, base),
               "one_language_pooled": sig.Design(len(g), (seeds, seeds), rho, base)}
    for name, design in designs.items():
        ratio = sig.mde(design, draws=power_draws) if 0 < base < 1 else None
        out[name] = {"hypotheses": design.hypotheses, "answers": list(design.sizes),
                     "icc": p3(design.icc), "odds_ratio": ratio and p3(ratio),
                     "pooled_rate_needed": ratio and p3(sig.pooled_rate(design, ratio)),
                     "rate_at_mean_hypothesis": ratio and p3(sig.shifted_rate(base, ratio))}
    return out


def lang_permutations(first, second, hyps, langs, draws):
    """Per language, the paired permutation of the cells' rates: each cell's change keeps its size
    and has its sign flipped. Holm over the languages."""
    rows, pvalues = [], []
    for lang in langs:
        strata = [pair(rate(first[h][lang]), rate(second[h][lang])) for h in hyps]
        changes = [b - a for (_, a), (_, b) in strata]
        rows.append({"mean_change": p3(sum(changes) / len(changes))})
        pvalues.append(sig.permutation_test(strata, sig.paired_shift, draws).p)
    return dict(zip(langs, adjusted(rows, pvalues)))


def cell_changes(first, second, langs, draws):
    """From grid first to grid second, per hypothesis and language cell: sign tests over all cells
    and per language, the per-language paired permutation, and over hypotheses a sign test and a
    paired permutation of their totals. Holm adjusts over the languages."""
    hyps = [h for h in first if h in second]
    diffs = {lang: [rate(second[h][lang]) - rate(first[h][lang]) for h in hyps] for lang in langs}
    totals = [pair(counted(first[h]), counted(second[h])) for h in hyps]
    return {"cells": paired(sig.sign_test([d for ds in diffs.values() for d in ds])),
            "cells_per_lang": dict(zip(langs, holm_paired(map(sig.sign_test, diffs.values())))),
            "cells_per_lang_permutation": lang_permutations(first, second, hyps, langs, draws),
            "by_hypothesis": paired(sig.sign_test([b - a for (_, a), (_, b) in totals])),
            "by_hypothesis_permutation": permuted(totals, sig.paired_shift, draws)}


def key(a):
    return a.hypothesis, a.lang, a.seed


def finished_pairs(before, after):
    """Answers of the hypotheses both runs finished, matched by hypothesis, language and seed."""
    done = {h for h in before.hypotheses
            if {before.outcome.get(h), after.outcome.get(h)} <= FINISHED}
    matched = {key(a): a for a in after.answers if a.hypothesis in done}
    return [(a, matched[key(a)]) for a in before.answers if key(a) in matched]


def answer_tests(pairs, langs):
    """Answer-level tests of without (first) against with (second), both treating the answers to a
    prompt as independent: exact McNemar on the seed pairs, and CMH stratified by prompt cell,
    which needs no pairing. Holm adjusts over the languages."""
    def mcnemar(selected):
        return sig.mcnemar([(x.confirmed, y.confirmed) for x, y in selected])

    def by_cell(selected):
        without, with_ = grid(x for x, _ in selected), grid(y for _, y in selected)
        return sig.cmh([table(without[h][lang], with_[h][lang])
                        for h in without for lang in without[h]])

    names = ("only_without", "only_with")
    by_lang = {lang: [p for p in pairs if p[0].lang == lang] for lang in langs}
    mcnemars = holm_paired(map(mcnemar, by_lang.values()), *names)
    strata = [by_cell(selected) for selected in by_lang.values()]
    cmhs = adjusted([{"odds_ratio": p3(t.odds_ratio)} for t in strata], [t.p for t in strata])
    overall = by_cell(pairs)
    return {"mcnemar": paired(mcnemar(pairs), *names),
            "cmh_by_cell": {"odds_ratio": p3(overall.odds_ratio), "p": p3(overall.p)},
            "per_lang": {lang: {"without": sum(x.confirmed for x, _ in selected),
                                "with": sum(y.confirmed for _, y in selected),
                                "mcnemar": m, "cmh_by_cell": c}
                         for (lang, selected), m, c in zip(by_lang.items(), mcnemars, cmhs)}}


def concordance(pairs):
    """Seed pairs that agree, beside the number expected if each cell's answers were matched at
    random: a cell of n answers with k and m counted agrees in (k m + (n - k)(n - m)) / n."""
    without, with_ = grid(x for x, _ in pairs), grid(y for _, y in pairs)
    expected = 0.0
    for h, by_lang in without.items():
        for lang, ys in by_lang.items():
            k, m, n = sum(ys), sum(with_[h][lang]), len(ys)
            expected += (k * m + (n - k) * (n - m)) / n
    return {"concordant": sum(x.confirmed == y.confirmed for x, y in pairs),
            "concordant_if_unpaired": round(expected, 1)}


def split_sample(run):
    """How far a rerun falls by selection alone: hypotheses chosen on one seed's answers by the
    harness's bar, as the run chose on all three, with the counted rate on that seed and on the
    other seeds' answers to the same prompts, pooled over the seeds. One seed is noisier than
    three, so the fall errs high."""
    by_hypothesis = {}
    for a in run.answers:
        by_hypothesis.setdefault(a.hypothesis, []).append(a)
    finished = {h: found for h, found in by_hypothesis.items() if run.outcome.get(h) in FINISHED}
    on, off, chosen = [], [], 0
    for seed in run.seeds:
        for found in finished.values():
            mine = [a for a in found if a.seed == seed]
            if rate([a.flagged for a in mine]) >= Config.min_rate:
                chosen += 1
                on += mine
                off += [a for a in found if a.seed != seed]

    def fall(lang):
        return p3(rate([a.confirmed for a in on if a.lang == lang])
                  - rate([a.confirmed for a in off if a.lang == lang]))
    choosing, other = rate([a.confirmed for a in on]), rate([a.confirmed for a in off])
    return {"chosen_per_seed": p3(chosen / len(run.seeds)), "choosing_seed": p3(choosing),
            "other_seeds": p3(other), "fall": p3(choosing - other),
            "fall_per_lang": {lang: fall(lang) for lang in run.langs}}


def selection(before, after, pairs):
    """How the retested hypotheses were chosen: by their outcome on the run before, where a finding
    has a raw flag rate of at least Config.min_rate over the answers that are the baseline here."""
    retested = Counter(before.outcome.get(h, "unknown") for h in after.hypotheses)
    left = Counter(before.outcome[h] for h in before.hypotheses
                   if h not in after.hypotheses and before.outcome.get(h) in FINISHED)
    return {"bar": Config.min_rate, "retested_by_outcome": dict(retested),
            "finished_not_retested": dict(left),
            "raw_flag_rate_before": p3(rate([x.flagged for x, _ in pairs])),
            "split_sample": split_sample(before)}


def mitigation(before, after, draws):
    """Without against with the system prompt over the hypotheses both runs finished."""
    pairs = finished_pairs(before, after)
    without, with_ = grid(x for x, _ in pairs), grid(y for _, y in pairs)
    return {"hypotheses": len(without), "pairs": len(pairs),
            "identical_prompts": sum(x.prompt == y.prompt for x, y in pairs),
            "counted_rate": [p3(rate([x.confirmed for x, _ in pairs])),
                             p3(rate([y.confirmed for _, y in pairs]))],
            "selection": selection(before, after, pairs), **concordance(pairs),
            **answer_tests(pairs, before.langs),
            **cell_changes(without, with_, before.langs, draws)}


def sizes(small, large, draws):
    """8B against 70B per hypothesis and language cell (cell_changes): the seeds of two models do
    not pair, and most prompts are the same. Hypotheses the 70B was never broken on have no
    verified answers; the report counts them as none of three in every cell, a variant given too."""
    gs, gl = grid(small.answers), grid(large.answers)
    langs = [lang for lang in small.langs if lang in large.langs]
    prompts = [{(a.hypothesis, a.lang): a.prompt for a in run.answers} for run in (small, large)]
    both = [(h, lang) for h in gs if h in gl for lang in langs]
    unbroken = {h: {lang: [0] * len(large.seeds) for lang in langs}
                for h in large.hypotheses if large.outcome.get(h) == "no_issue"}
    with_unbroken = gl | unbroken
    return {"hypotheses": len(both) // len(langs), "cells_compared": len(both),
            "identical_prompts": sum(prompts[0][cell] == prompts[1][cell] for cell in both),
            **cell_changes(gs, gl, langs, draws),
            "unbroken_as_none": {"hypotheses": sum(h in with_unbroken for h in gs),
                                 **cell_changes(gs, with_unbroken, langs, draws)}}


def load(run_id, cache_root):
    found = paths.run_dir(run_id)
    if found is None:
        raise SystemExit(f"run {run_id} not found in {paths.RUNS} or {paths.SHIPPED}")
    control = found / "control.json"
    rows = json.loads(control.read_text()) if control.is_file() else []
    return answers.load_run(found, HYPOTHESES, cache_root), rows


def run_numbers(run, rows, cache_root, draws, power_draws):
    g = grid(run.answers)
    out = {"coverage": coverage(run), "language_effect": language_effect(g, draws),
           "english_vs": english_vs(g), "different_truths": different_truths(g, draws),
           "per_hypothesis": per_hypothesis(g) | {"reading": {
               h: text for (r, h), text in DOUBTS.items() if r == run.id}},
           "detectable": detectable(g, power_draws)}
    if rows:
        neutral = answers.neutral_answers(rows, HYPOTHESES, run, cache_root)
        out["control_truths"] = control_truths(run, rows, neutral, draws)
    return out


def main(out=OUT, report=REPORT, cache_root=CACHE_DIR, ids=(SMALL, LARGE, MITIGATED),
         draws=sig.DRAWS, power_draws=sig.POWER_DRAWS):
    (small, small_rows), (large, large_rows), (mitigated, _) = (load(i, cache_root) for i in ids)
    numbers = {"script": "scripts/report_stats.py", "draws": draws, "seed": sig.SEED,
               "power_draws": power_draws,
               "models": {run.id: run.model + (" with a system prompt" if run.system else "")
                          for run in (small, large, mitigated)},
               "runs": {small.id: run_numbers(small, small_rows, cache_root, draws, power_draws),
                        large.id: run_numbers(large, large_rows, cache_root, draws, power_draws)},
               "mitigation": {"runs": [large.id, mitigated.id],
                              **mitigation(large, mitigated, draws)},
               "sizes": {"runs": [small.id, large.id], **sizes(small, large, draws)},
               "report_claims": claims(report.read_text())}
    out.mkdir(parents=True, exist_ok=True)
    (out / "stats.json").write_text(json.dumps(numbers, indent=1, ensure_ascii=False) + "\n")
    (out / "stats.md").write_text(markdown(numbers))
    return numbers


# The reading note and the inventory of the report's intervals and tests, kept together below so
# they can move to a module of their own.

# Each interval or test the report states: words that find it, then a reading written by hand of
# how it is computed, what it rests on, and whether it treats answers (or clips) as independent.
# Only the line numbers are computed, so a changed report can leave a reading stale.
CLAIMS = [
    (["difference −14 points, 95% CI −23 to −5", "(−7 points, 95% CI −20 to +7)"],
     "bootstrap of the pooled difference over hypotheses", "hypotheses as clusters", False),
    (["significant only in English, Swiss"], "six per-language bootstrap intervals read as tests, "
     "with no multiplicity adjustment (item 5 gives the cell permutation, Holm over six)",
     "hypotheses as clusters", False),
    (["Wrong answers (95% CI)", "74% (52–92)", "83% (50–100)", "71% (38–96)", "64% (28–89)",
      "never narrower than Wilson"], "bootstrap over variations x languages; 1 and 2 variations "
     "in findings 2 and 4", "variations and languages as clusters, floored at Wilson", False),
    (["48% (95% CI 36–60)", "48% (36–60)", "against 1% (0–3)"],
     "bootstrap over 8 dialects (one speaker each) x 60 sentences",
     "dialects and sentences as clusters", False),
    (["**Figure 1.**", "**Figure 4.**"], "pooled rate per language, bootstrap over hypotheses",
     "hypotheses as clusters", False),
    (["**Figure 2.**"], "Wilson interval of each hypothesis's 18 answers (6 prompts x 3 seeds)",
     "independent answers, though three share each prompt, so it is too narrow", True),
    (["**Figure 3.**"], "Wilson interval of each dialect's 60 clips of 60 distinct sentences",
     "independent clips, fair for distinct sentences; one speaker per dialect, so it covers that "
     "speaker, not the dialect", True),
    (["Cohen's κ, agreement beyond", "κ 0.14"], "point estimates, no interval", "none stated",
     False),
    (["from 29% to 12% (Romansh 52% to 14%)"], "rates, no interval or test in the text",
     "none stated", False),
]
INTERVAL = re.compile(r"95% CI|\(\d+–\d+\)|significan|κ")


def claims(report):
    """CLAIMS with the report lines that state each, and the lines that look like an interval or
    a test but match none of them."""
    lines = report.splitlines()
    found = [{"lines": [i + 1 for i, line in enumerate(lines) if any(w in line for w in words)],
              "states": words, "reading": {"method": method, "rests_on": rests_on,
                                           "assumes_independence": independent}}
             for words, method, rests_on, independent in CLAIMS]
    seen = {n for claim in found for n in claim["lines"]}
    return {"claims": found, "unlisted_lines": [i + 1 for i, line in enumerate(lines)
                                                if INTERVAL.search(line) and i + 1 not in seen]}


def grid_table(header, rows):
    return [f"| {' | '.join(header)} |", "|" + "---|" * len(header),
            *(f"| {' | '.join(map(str, r))} |" for r in rows), ""]


def section(title, notes, header, rows):
    return [f"## {title}", "", *(line for note in notes for line in (note, "")),
            *grid_table(header, rows)]


def split(t, first="higher", second="lower"):
    holm = f" (Holm {t['p_holm']})" if "p_holm" in t else ""
    return f"{t[first]}/{t[second]}, p {t['p']}{holm}"


def with_holm(t):
    return f"{t['p']} (Holm {t['p_holm']})"


def significant(rows, key="p_holm"):
    """The names whose p (Holm-adjusted by default) is below ALPHA, or "none"."""
    return ", ".join(name for name, t in rows.items() if t[key] < ALPHA) or "none"


def preamble(n):
    models = "; ".join(f"`{r}` {model}" for r, model in n["models"].items())
    covered = []
    for r, x in n["runs"].items():
        left = ", ".join(f"{h} ({o})" for h, o in x["coverage"]["left_out"].items())
        covered.append(f"`{r}` {x['coverage']['hypotheses']}" + (f", left out: {left}" if left
                                                                  else ""))
    return ["# Statistics audit", "",
            f"Written by `{n['script']}`; every number is in `stats.json`. Runs: {models}. Every "
            "test here was chosen after the runs were read, so all are post hoc.", "",
            "An answer counts by Answer.confirmed, which is the judge's verdict. The language "
            "effects (items 1, 2, 3 and 6) assume the judge scores every language alike; a "
            "difference between languages can come from the judge as well as from the model, and "
            "item 6 names a case against that assumption.", "",
            f"Hypotheses with verified answers: {'; '.join(covered)}. The report's pooled figures "
            "use 40 hypotheses on both models (the 70B's failed one left out of both, its "
            "never-broken ones counted as correct), so its rates differ slightly from these.", "",
            f"Permutation tests use {n['draws']} shuffles with seed {n['seed']}; 0.0001 means no "
            "shuffle reached the observed value. The variance and split-count tests take the upper "
            "tail of a statistic without direction; the paired permutations flip the sign of each "
            "change and are two-sided, as are all other tests.", ""]


def language_sections(runs):
    effect = [(r, " ".join(f"{k} {v:.2f}" for k, v in x["language_effect"]["rates"].items()),
               x["language_effect"]["cells_shuffled"]["p"],
               x["language_effect"]["answers_shuffled"]["p"]) for r, x in runs.items()]
    english = [(r, lang, t["odds_ratio"], with_holm(t), split(t["sign"]))
               for r, x in runs.items() for lang, t in x["english_vs"].items()]
    return [*section("1. Six-language effect: variance of the pooled language rates",
                     ["Shuffling whole cells keeps the three answers to a prompt together; "
                      "shuffling single answers treats them as independent."],
                     ["run", "rates", "p, prompt cells shuffled", "p, single answers shuffled"],
                     effect),
            *section("2. Each language against English, Holm over the five",
                     ["CMH is stratified by hypothesis but treats the answers within one as "
                      "independent; the sign test on the right counts hypotheses."],
                     ["run", "lang", "MH odds ratio", "CMH p", "hypotheses higher/lower"],
                     english)]


def truths_section(runs):
    rows, contrasts, logged = [], [], []
    for r, x in runs.items():
        named = [("premise, all hypotheses", x["different_truths"])]
        control = x.get("control_truths")
        if control:
            named += [("premise, same hypotheses", control["premise_same_hypotheses"]),
                      ("neutral", control["neutral"])]
            contrasts.append(f"`{r}` {split(control['split_in_one_only'], 'premise', 'neutral')}")
            logged.append("{} of {}".format(*control["logged_rates_equal_raw_flags"]))
        rows += [(r, name, t["hypotheses"], t["observed"], t["expected"], t["p"])
                 for name, t in named]
    notes = ["The null shuffles single answers between the languages of a hypothesis. Shuffling "
             "whole cells cannot change the count, which depends only on each hypothesis's set of "
             "cell totals, so no null keeps a prompt's answers together; p here mostly measures "
             "how closely the answers to one prompt agree, which the cell ICC in item 7 shows too. "
             "Language and prompt are confounded.",
             "Both conditions show an excess over the null. Hypotheses split under one condition "
             f"only (premise/neutral, McNemar): {'; '.join(contrasts)}. A p above 0.05 means no "
             "detectable difference between the conditions, not equal counts.",
             "control.json keeps only per-language rates of raw flags (equal to the replayed flags "
             f"in {', '.join(logged)} cells), so the control's verdicts are replayed from the LLM "
             "cache and counted like the findings."]
    return section("3. Different truths: one language at 3/3 and another at 0/3", notes,
                   ["run", "answers", "hypotheses", "observed", "expected", "p"], rows)


def mitigation_section(m):
    pick, chosen = m["selection"], m["selection"]["split_sample"]
    names = ("only_without", "only_with")
    rows = [(lang, f"{t['without']}/{t['with']}", split(t["mcnemar"], *names),
             with_holm(t["cmh_by_cell"]), split(m["cells_per_lang"][lang]),
             f"{m['cells_per_lang_permutation'][lang]['mean_change']}, "
             f"p {with_holm(m['cells_per_lang_permutation'][lang])}",
             chosen["fall_per_lang"][lang]) for lang, t in m["per_lang"].items()]
    outcomes = ", ".join(f"{k} {v}" for k, v in pick["retested_by_outcome"].items())
    left = ", ".join(f"{k} {v}" for k, v in pick["finished_not_retested"].items()) or "none"
    by_test = {"McNemar": {k: t["mcnemar"] for k, t in m["per_lang"].items()},
               "CMH by cell": {k: t["cmh_by_cell"] for k, t in m["per_lang"].items()},
               "cell sign test": m["cells_per_lang"],
               "cell permutation": m["cells_per_lang_permutation"]}
    notes = [f"{m['pairs']} answer pairs from the {m['hypotheses']} hypotheses both runs finished, "
             f"{m['identical_prompts']} with byte-identical prompts; counted rate "
             f"{m['counted_rate'][0]} without and {m['counted_rate'][1]} with the prompt.",
             "Selection: the run with the prompt retested hypotheses by their outcome on "
             f"`{m['runs'][0]}` ({outcomes}; finished but not retested: {left}). A finding there "
             f"has a raw flag rate of at least {pick['bar']} over the very answers that are the "
             f"baseline here (theirs: {pick['raw_flag_rate_before']}), so even an unchanged rerun "
             "would fall somewhat. Split sample on that run: choosing by the same bar on one seed "
             f"keeps {chosen['chosen_per_seed']} hypotheses per seed, counted at "
             f"{chosen['choosing_seed']} on the choosing seed against {chosen['other_seeds']} on "
             f"the other two seeds of the same prompts, a fall of {chosen['fall']} by selection "
             "alone (one seed is noisier than three, so this errs high; per language in the last "
             "column).",
             f"Answers, all languages: McNemar {split(m['mcnemar'], *names)}; CMH by prompt cell "
             f"p {m['cmh_by_cell']['p']}. Both treat the three answers to a prompt as independent. "
             "McNemar pairs answers by seed number only: a system message changes the sampled "
             f"text, and the {m['concordant']} concordant pairs are close to the "
             f"{m['concordant_if_unpaired']} expected if each cell's answers were matched at "
             "random. CMH by cell needs no pairing.",
             f"Cells (a prompt's three answers as one rate, though cells of one hypothesis are not "
             f"independent): higher/lower {split(m['cells'])}. Hypotheses higher/lower "
             f"{split(m['by_hypothesis'])}; paired permutation of their totals p "
             f"{m['by_hypothesis_permutation']['p']}.",
             "Below 0.05 after Holm over the six languages: " + "; ".join(
                 f"{name} {significant(results)}" for name, results in by_test.items()) + "."]
    return section(f"4. Mitigation: `{m['runs'][0]}` without, `{m['runs'][1]}` with the prompt",
                   notes, ["lang", "counted without/with", "McNemar only without/only with",
                           "CMH by cell p", "cells higher/lower, sign test",
                           "cells, mean change and permutation p", "fall by selection"], rows)


def sizes_section(s):
    variant = s["unbroken_as_none"]
    rows = [(lang, split(t), f"{s['cells_per_lang_permutation'][lang]['mean_change']}, p "
             f"{with_holm(s['cells_per_lang_permutation'][lang])}",
             split(variant["cells_per_lang"][lang])) for lang, t in s["cells_per_lang"].items()]
    notes = [f"{s['cells_compared']} cells of {s['hypotheses']} hypotheses, "
             f"{s['identical_prompts']} with byte-identical prompts; the seeds of two models do "
             f"not pair. Cells higher/lower: {split(s['cells'])}, though cells of one hypothesis "
             f"are not independent. Hypotheses higher/lower: {split(s['by_hypothesis'])}; paired "
             f"permutation of their totals: p {s['by_hypothesis_permutation']['p']}.",
             "Counting the 70B's never-broken hypotheses as none of three, as the report does "
             f"({variant['hypotheses']} hypotheses): hypotheses higher/lower "
             f"{split(variant['by_hypothesis'])}; paired permutation p "
             f"{variant['by_hypothesis_permutation']['p']}; cells per language in the last column.",
             "Per language the sign test drops the size of each change and every tied cell, so it "
             "is much weaker than the paired permutation of the same cells, which is the closer "
             "match to the report's per-language bootstrap intervals. Permutation p below 0.05: "
             f"{significant(s['cells_per_lang_permutation'], 'p')} before Holm, "
             f"{significant(s['cells_per_lang_permutation'])} after Holm over six."]
    return section(f"5. 8B `{s['runs'][0]}` against 70B `{s['runs'][1]}`", notes,
                   ["lang", "cells higher/lower on the 70B, sign test",
                    "cells, mean change and permutation p",
                    f"{variant['hypotheses']} hypotheses: cells higher/lower"], rows)


def hypothesis_section(runs):
    summary = []
    for r, x in runs.items():
        t = x["per_hypothesis"]
        summary.append((r, t["hypotheses"], len(t["below_alpha"]),
                        ", ".join(t["holm_below_alpha"]) or "none", t["tarone_family"],
                        ", ".join(t["tarone_below_alpha"]) or "none",
                        f"{t['floor_p']} (Holm {t['floor_p_holm']})"))
    below = [(r, b["hypothesis"], b["english"], b["others"], b["p"], b["p_holm"], b["p_tarone"])
             for r, x in runs.items() for b in x["per_hypothesis"]["below_alpha"]]
    doubts = [f"`{r}` {h}: {text}." for r, x in runs.items()
              for h, text in x["per_hypothesis"]["reading"].items()]
    first = next(iter(runs.values()))["per_hypothesis"]
    notes = [f"{first['test']}, of English (3 answers) against the other five languages (15) "
             "within each hypothesis. There English is one prompt answered three times and the "
             "others are five prompts, so a small p shows that one English prompt drew other "
             "answers than five other prompts, with the seeds as the only replication; it does not "
             "show a language effect. With whole cells shuffled, no hypothesis could reach p below "
             f"{first['cell_floor_p']}.",
             f"No split reaches p below {first['floor_p']}. Holm over all hypotheses "
             "multiplies that by their number (last column; above 0.05, none can survive). "
             "Hypotheses whose answers all agree can never reach significance; Tarone's family "
             "counts only those whose margins can reach alpha / m, and Bonferroni then divides "
             "alpha by that m.",
             " ".join(["The splits are the judge's verdicts.", *(
                 ["These need a human read before any is cited:", *doubts] if doubts else [])])]
    return [*section("6. English against the other five within each hypothesis", notes,
                     ["run", "hypotheses", "raw p < 0.05", "Holm over all, p < 0.05",
                      "Tarone family", "Tarone, p < 0.05", "smallest possible p"], summary),
            *grid_table(["run", "hypothesis", "English", "others", "p", "Holm", "Tarone"], below)]


def limit_sections(runs, report):
    rows = []
    for r, x in runs.items():
        t = x["detectable"]
        rows += [(r, t["english_rate"], f"{t['icc_hypothesis']} / {t['icc_cell']}", name,
                  t[name]["odds_ratio"], t[name]["pooled_rate_needed"],
                  t[name]["rate_at_mean_hypothesis"])
                 for name in ("one_hypothesis", "one_language_pooled")]
    listed = [(", ".join(map(str, c["lines"])) or "not found", c["reading"]["method"],
               c["reading"]["rests_on"], "yes" if c["reading"]["assumes_independence"] else "no")
              for c in report["claims"]]
    unlisted = ", ".join(map(str, report["unlisted_lines"])) or "none"
    return [*section("7. Minimum detectable effect against English, 80% power at alpha 0.05",
                     ["One hypothesis: 3 answers in one language against 15 in the others, "
                      "Fisher's exact test. Pooled: 3 against 3 in every hypothesis, rates drawn "
                      "from a beta distribution with the hypothesis ICC, CMH. The odds ratio holds "
                      "within each hypothesis and odds ratios do not average, so the pooled rate "
                      "a language needs is the mean over the drawn hypotheses, below the rate of a "
                      "hypothesis at the English mean. Answers are simulated as independent given "
                      "their hypothesis, but the three answers to a prompt agree more (cell ICC), "
                      "so these are lower bounds."],
                     ["run", "English rate", "ICC hypothesis / cell", "design", "odds ratio",
                      "pooled rate needed", "rate at the mean hypothesis"], rows),
            *section("8. Intervals and tests the report states",
                     ["Method and what it rests on are a reading written by hand; only the line "
                      f"numbers are computed. Unlisted lines that look like an interval: "
                      f"{unlisted}."],
                     ["report lines", "method", "rests on", "assumes independence"], listed)]


def markdown(n):
    return "\n".join([*preamble(n), *language_sections(n["runs"]), *truths_section(n["runs"]),
                      *mitigation_section(n["mitigation"]), *sizes_section(n["sizes"]),
                      *hypothesis_section(n["runs"]), *limit_sections(n["runs"],
                                                                      n["report_claims"])])


if __name__ == "__main__":
    main()
