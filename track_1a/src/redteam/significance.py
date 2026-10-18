"""Tests for answers nested in hypotheses. The three answers to one prompt are not three independent
users and hypotheses differ in difficulty, so these tests stratify by hypothesis, shuffle labels
only within one, or compare whole cells. Random draws have fixed seeds, so reruns agree.
"""
from __future__ import annotations

import random
from collections import defaultdict
from math import comb, erfc, exp, inf, isclose, log, nan, sqrt
from typing import NamedTuple

DRAWS, SEED = 10_000, 1
POWER_DRAWS, STEPS = 2000, 12  # per power estimate; bisection steps on the log odds ratio


class Stratified(NamedTuple):
    statistic: float
    p: float
    odds_ratio: float


class Paired(NamedTuple):
    first: int  # pairs, or differences, that favour the first side
    second: int
    p: float


class Permutation(NamedTuple):
    observed: float
    expected: float  # mean of the statistic over the shuffles
    p: float


class Design(NamedTuple):
    hypotheses: int
    sizes: tuple[int, int]  # answers per hypothesis in the first and the second group
    icc: float  # correlation of two answers to the same hypothesis
    base: float  # the first group's mean rate, strictly between 0 and 1


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


def permutation_test(strata, statistic, draws: int = DRAWS, seed: int = SEED) -> Permutation:
    """How unusual statistic(strata) is when labels are shuffled within each stratum, a list of
    (label, unit) pairs. p is the upper tail: the share of shuffles at least as large as the
    observed value, counting the observed arrangement as one of them, so p is never 0."""
    observed = statistic(strata)
    rng = random.Random(seed)
    labels = [[label for label, _ in stratum] for stratum in strata]
    units = [[unit for _, unit in stratum] for stratum in strata]
    total = at_least = 0
    for _ in range(draws):
        for row in labels:
            rng.shuffle(row)
        value = statistic([list(zip(row, kept)) for row, kept in zip(labels, units)])
        total += value
        at_least += value > observed or isclose(value, observed)
    return Permutation(observed, total / draws, (at_least + 1) / (draws + 1))


def label_totals(stratum) -> dict:
    """Units (k, n) summed per label: label -> [k, n]."""
    totals = defaultdict(lambda: [0, 0])
    for label, (k, n) in stratum:
        totals[label][0] += k
        totals[label][1] += n
    return totals


def rate_variance(strata) -> float:
    """Variance across labels of each label's rate pooled over all strata; units are (k, n)."""
    rates = [k / n for k, n in label_totals([p for stratum in strata for p in stratum]).values()]
    mean = sum(rates) / len(rates)
    return sum((r - mean) ** 2 for r in rates) / len(rates)


def split_strata(strata) -> int:
    """Strata in which every unit of one label counts and none of another label's does."""
    split = 0
    for stratum in strata:
        totals = label_totals(stratum).values()
        split += any(k == n for k, n in totals) and any(k == 0 for k, _ in totals)
    return split


def paired_shift(strata) -> float:
    """|sum of "second" minus "first"| over strata of two numbers: shuffled, a two-sided test."""
    return abs(sum(dict(stratum)["second"] - dict(stratum)["first"] for stratum in strata))


def icc(groups) -> float:
    """Intra-cluster correlation from a one-way ANOVA, n0 standing in for unequal group sizes."""
    sizes = [len(g) for g in groups]
    total, k = sum(sizes), len(groups)
    if k < 2 or total == k:  # nothing between groups, or nothing within one, to compare
        return 0.0
    means = [sum(g) / len(g) for g in groups]
    grand = sum(map(sum, groups)) / total
    between = sum(s * (m - grand) ** 2 for s, m in zip(sizes, means)) / (k - 1)
    within = sum((x - m) ** 2 for g, m in zip(groups, means) for x in g) / (total - k)
    n0 = (total - sum(s * s for s in sizes) / total) / (k - 1)
    spread = between + (n0 - 1) * within
    return (between - within) / spread if spread else 0.0


def hypothesis_rate(rng: random.Random, base: float, correlation: float) -> float:
    """A rate from the beta distribution with mean base whose answers correlate by correlation."""
    if correlation <= 0:
        return base
    if correlation >= 1:  # every answer to a hypothesis alike
        return float(rng.random() < base)
    size = 1 / correlation - 1
    return rng.betavariate(base * size, (1 - base) * size)


def shifted_rate(base: float, odds_ratio: float) -> float:
    """The rate whose odds are base's odds times odds_ratio."""
    return base * odds_ratio / (base * odds_ratio + 1 - base)


def pooled_rate(design: Design, odds_ratio: float, draws: int = 100_000,
                seed: int = SEED) -> float:
    """The second group's rate pooled over hypotheses whose odds are each odds_ratio times the
    first group's: the mean over drawn hypotheses, as an odds ratio does not carry over to means."""
    rng = random.Random(seed)
    rates = (hypothesis_rate(rng, design.base, design.icc) for _ in range(draws))
    return sum(shifted_rate(rate, odds_ratio) for rate in rates) / draws


def power(design: Design, odds_ratio: float, alpha: float = 0.05, draws: int = POWER_DRAWS,
          seed: int = SEED) -> float:
    """Share of simulated studies that find the difference at alpha, by fisher for one hypothesis
    and cmh for several: each hypothesis draws a rate, the second group has odds_ratio times its
    odds, and answers are independent given it."""
    rng = random.Random(seed)
    first, second = design.sizes
    found = 0
    for _ in range(draws):
        tables = []
        for _ in range(design.hypotheses):
            rate = hypothesis_rate(rng, design.base, design.icc)
            k1 = sum(rng.random() < rate for _ in range(first))
            k2 = sum(rng.random() < shifted_rate(rate, odds_ratio) for _ in range(second))
            tables.append((k2, second - k2, k1, first - k1))
        found += (fisher(*tables[0]) if len(tables) == 1 else cmh(tables).p) < alpha
    return found / draws


def mde(design: Design, target: float = 0.8, alpha: float = 0.05, draws: int = POWER_DRAWS,
        seed: int = SEED, largest: float = 1e4) -> float | None:
    """The smallest odds ratio that power finds with the target power, by bisection on its
    logarithm with the same draws at every step; None when even the largest falls short."""
    if power(design, largest, alpha, draws, seed) < target:
        return None
    low, high = 0.0, log(largest)
    for _ in range(STEPS):
        middle = (low + high) / 2
        if power(design, exp(middle), alpha, draws, seed) >= target:
            high = middle
        else:
            low = middle
    return exp(high)
