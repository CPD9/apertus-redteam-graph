"""Tests on counts: CMH over the 2x2 tables of several strata, Fisher's exact test of one,
McNemar and the sign test of paired counts, and the Holm and Tarone adjustments for running
many of them. significance.py builds on these and is where the analyses import them from.
"""
from __future__ import annotations

from math import comb, erfc, inf, nan, sqrt
from typing import NamedTuple


class Stratified(NamedTuple):
    statistic: float
    p: float
    odds_ratio: float


class Paired(NamedTuple):
    first: int  # pairs, or differences, that favour the first side
    second: int
    p: float


def cmh(tables, correct: bool = True) -> Stratified:
    """Cochran-Mantel-Haenszel test over 2x2 tables (a, b, c, d), one per stratum: a, b count the
    first group's answers that count and that do not, c, d the second group's; the common odds
    ratio is the first group's against the second's. Strata under two answers are skipped."""
    deviation = variance = upper = lower = 0.0
    for a, b, c, d in tables:
        n = a + b + c + d
        if n < 2:
            continue
        deviation += a - (a + b) * (a + c) / n
        variance += (a + b) * (c + d) * (a + c) * (b + d) / (n * n * (n - 1))
        upper += a * d / n
        lower += b * c / n
    ratio = upper / lower if lower else (inf if upper else nan)
    if variance == 0:
        return Stratified(0.0, 1.0, ratio)
    statistic = max(abs(deviation) - (0.5 if correct else 0.0), 0.0) ** 2 / variance
    return Stratified(statistic, erfc(sqrt(statistic / 2)), ratio)  # chi-square tail, 1 df


def fisher(a: int, b: int, c: int, d: int) -> float:
    """Fisher's exact two-sided p of one table laid out as in cmh: the chance, margins fixed, of a
    table no more likely than this one. For one small table, where cmh's chi-square is rough."""
    first, counted, n = a + b, a + c, a + b + c + d

    def weight(x):
        return comb(first, x) * comb(n - first, counted - x)
    tables = range(max(0, counted - (n - first)), min(first, counted) + 1)
    return sum(w for w in map(weight, tables) if w <= weight(a)) / comb(n, counted)


def fisher_floor(first: int, second: int, counted: int) -> float:
    """The smallest p fisher gives any table with these margins: group sizes, answers counted."""
    tables = range(max(0, counted - second), min(first, counted) + 1)
    return min(fisher(a, first - a, counted - a, second - counted + a) for a in tables)


def tarone(floors: list[float], alpha: float = 0.05) -> int:
    """Tarone's family size for discrete tests whose smallest reachable p values are floors: the
    smallest m with at most m floors below alpha / m. A test that cannot reach it needs no alpha."""
    return next((m for m in range(1, len(floors) + 1)
                 if sum(f < alpha / m for f in floors) <= m), 0)


def binomial_p(k: int, n: int) -> float:
    """Exact two-sided p of k successes in n trials that each succeed with probability 1/2."""
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(k, n - k) + 1)) / 2 ** n)


def mcnemar(pairs) -> Paired:
    """Exact McNemar test of (first, second) yes/no pairs; Paired.first: yes on the first only."""
    only_first = sum(1 for x, y in pairs if x and not y)
    only_second = sum(1 for x, y in pairs if y and not x)
    return Paired(only_first, only_second, binomial_p(only_first, only_first + only_second))


def sign_test(differences) -> Paired:
    """Exact sign test: how many differences are above and below zero, ties left out."""
    above = sum(1 for d in differences if d > 0)
    below = sum(1 for d in differences if d < 0)
    return Paired(above, below, binomial_p(above, above + below))


def holm(pvalues: list[float]) -> list[float]:
    """Holm's step-down adjustment, returned in the order given."""
    order = sorted(range(len(pvalues)), key=pvalues.__getitem__)
    adjusted, running = [1.0] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(pvalues) - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted
