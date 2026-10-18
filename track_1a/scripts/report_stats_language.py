"""The language effects within one run: the six languages against each other and against English,
hypotheses split between languages beside the neutral control, and the smallest effect against
English that the design can find.
"""
from __future__ import annotations

from report_stats_grid import (ALPHA, adjusted, cells, grid, holm_paired, p3, paired, permuted,
                               rate, singles, table, units)

from redteam import significance as sig


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
