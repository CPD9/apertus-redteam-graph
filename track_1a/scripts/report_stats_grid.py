"""Answers as the statistics audit counts them, a grid of counted answers by hypothesis and
language, and the helpers that turn the tests of redteam.significance into JSON.
"""
from __future__ import annotations

from math import isfinite

from redteam import significance as sig

ALPHA = 0.05


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
