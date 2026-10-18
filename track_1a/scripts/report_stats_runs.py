"""Two runs set against each other, per hypothesis and language cell: without and with the
mitigation system prompt, whose answers also pair by seed, and the 8B against the 70B, whose
seeds do not pair.
"""
from __future__ import annotations

from collections import Counter

from report_stats_grid import (adjusted, counted, grid, holm_paired, p3, pair, paired, permuted,
                               rate, table)

from redteam import significance as sig
from redteam.graph import Config

FINISHED = {"finding", "not_reproducible"}  # the verifier logged every answer of the hypothesis


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
