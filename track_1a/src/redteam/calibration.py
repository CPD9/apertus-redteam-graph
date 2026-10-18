"""How well a judge's count matches a reference labelling, and the counted rate corrected for it.

Sensitivity (Se) is the share of the answers the reference says assert the error that the judge
counts; specificity (Sp) the share of the others that it leaves out. The Rogan-Gladen estimator
turns a counted rate q into the rate the reference would give, p = (q + Sp - 1) / (Se + Sp - 1).
That holds only as far as the reference is right and Se and Sp carry over from the answers the
reference labels to the answers counted. A p outside [0, 1] says they do not, which clipping
would hide, so p is kept unclipped. The answers to one hypothesis share a prompt and the judge's
errors gather in a few hypotheses, so every interval but Wilson's resamples clusters.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from .stats import wilson

# As scripts/report_pooling.py, which gives the scorer's intervals on the same answers. Fixed, so
# rerunning the report does not move the intervals.
DRAWS, SEED = 4000, 1


@dataclass(frozen=True)
class Confusion:
    """The judge's count against the reference: tp counted and asserts, fn missed, tn left out
    and does not assert, fp counted though it does not."""
    tp: int = 0
    fn: int = 0
    tn: int = 0
    fp: int = 0

    def __add__(self, other: Confusion) -> Confusion:
        return Confusion(self.tp + other.tp, self.fn + other.fn, self.tn + other.tn,
                         self.fp + other.fp)

    def times(self, weight: int) -> Confusion:
        return Confusion(weight * self.tp, weight * self.fn, weight * self.tn, weight * self.fp)

    @property
    def asserting(self) -> int:
        return self.tp + self.fn

    @property
    def other(self) -> int:
        return self.tn + self.fp


def confusion(pairs) -> Confusion:
    """From (judge counts, reference says it asserts the error) pairs."""
    cells = Counter((bool(judge), bool(reference)) for judge, reference in pairs)
    return Confusion(cells[True, True], cells[False, True], cells[False, False], cells[True, False])


def sensitivity(c: Confusion) -> float | None:
    return c.tp / c.asserting if c.asserting else None


def specificity(c: Confusion) -> float | None:
    return c.tn / c.other if c.other else None


def share(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": round(k / n, 3) if n else None,
            "ci95": [round(x, 3) for x in wilson(k, n)]}


def pooled(confusions: list[Confusion], weights: Counter) -> Confusion:
    return sum((confusions[i].times(w) for i, w in weights.items()), Confusion())


def side(k: int, n: int, hypotheses: int, drawn: list[float | None]) -> dict:
    """k of n with its Wilson interval, which takes the answers as independent, and the interval
    over the resampled hypotheses, which does not, from the draws with an answer on this side."""
    values = [x for x in drawn if x is not None]
    return {**share(k, n), "hypotheses": hypotheses, "cluster_ci95": interval(values),
            "cluster_draws": len(values)}


def accuracy(confusions: list[Confusion], draws: int = DRAWS, seed: int = SEED) -> dict:
    """Se and Sp from one confusion per hypothesis, how many hypotheses have answers on each side,
    and Youden's index Se + Sp - 1."""
    total = sum(confusions, Confusion())
    drawn = [pooled(confusions, d[0]) for d in resamples([len(confusions)], draws, seed)]
    se, sp = sensitivity(total), specificity(total)
    return {"sensitivity": side(total.tp, total.asserting, sum(c.asserting > 0 for c in confusions),
                                [sensitivity(c) for c in drawn]),
            "specificity": side(total.tn, total.other, sum(c.other > 0 for c in confusions),
                                [specificity(c) for c in drawn]),
            "youden": None if se is None or sp is None else round(se + sp - 1, 3)}


def rogan_gladen(q: float, se: float, sp: float) -> float | None:
    """The rate behind a counted rate q, unclipped. None when Se + Sp <= 1: the judge then
    separates the reference's two classes no better than chance and the formula is void."""
    youden = se + sp - 1
    return (q + sp - 1) / youden if youden > 0 else None


def clip(p: float | None) -> float | None:
    return None if p is None else min(1.0, max(0.0, p))


@dataclass(frozen=True)
class Cluster:
    """One hypothesis: how many of its answers the judge counts, out of how many, and the judge's
    confusion on those of its answers the reference labels."""
    counted: int
    answers: int
    confusion: Confusion = Confusion()


def estimate(clusters: list[Cluster], weights: Counter | None = None) -> tuple[float, float | None]:
    """The counted rate over the clusters, each taken as often as weights says, and that rate
    corrected by the Se and Sp of the same clusters. None when Se or Sp cannot be had."""
    weights = Counter(range(len(clusters))) if weights is None else weights
    counted = sum(w * clusters[i].counted for i, w in weights.items())
    answers = sum(w * clusters[i].answers for i, w in weights.items())
    c = pooled([cluster.confusion for cluster in clusters], weights)
    q, se, sp = counted / answers, sensitivity(c), specificity(c)
    return q, None if se is None or sp is None else rogan_gladen(q, se, sp)


def resamples(sizes: list[int], draws: int = DRAWS, seed: int = SEED) -> list[list[Counter]]:
    """Per draw and stratum, how often each cluster is drawn. Strata are drawn apart, so every
    draw has as many clusters of each stratum as the data."""
    rng = random.Random(seed)
    return [[Counter(rng.choices(range(n), k=n)) for n in sizes] for _ in range(draws)]


def bootstrap(strata: list[list[Cluster]], draws: int = DRAWS,
              seed: int = SEED) -> list[tuple[float, float | None]]:
    """estimate() on every draw of a cluster bootstrap that resamples hypotheses within each
    stratum. The same strata sizes and seed give the same draws, so two calls pair up."""
    flat = [c for stratum in strata for c in stratum]
    starts = [sum(len(s) for s in strata[:k]) for k in range(len(strata))]
    out = []
    for drawn in resamples([len(s) for s in strata], draws, seed):
        weights = Counter()
        for start, counts in zip(starts, drawn):
            weights.update({start + i: w for i, w in counts.items()})
        out.append(estimate(flat, weights))
    return out


def crossed_bootstrap(cells: dict[tuple, object], statistic, draws: int = DRAWS,
                      seed: int = SEED) -> list:
    """statistic on the cell values of every draw that resamples the two kinds of cluster in the
    keys apart, e.g. dialects and sentences, as stats.cluster_bootstrap does for a mean: a cell is
    taken as often as its row times its column. Draws where statistic gives None are left out."""
    rows, cols = sorted({a for a, _ in cells}), sorted({b for _, b in cells})
    rng = random.Random(seed)
    out = []
    for _ in range(draws):
        row_weight = Counter(rng.choices(rows, k=len(rows)))
        col_weight = Counter(rng.choices(cols, k=len(cols)))
        value = statistic([v for (a, b), v in cells.items()
                           for _ in range(row_weight[a] * col_weight[b])])
        if value is not None:
            out.append(value)
    return out


def interval(values: list[float]) -> list[float] | None:
    """The 2.5th and 97.5th percentile, None without values."""
    if not values:
        return None
    values = sorted(values)
    return [round(values[round(q * (len(values) - 1))], 3) for q in (0.025, 0.975)]


def worst_first(scores: dict[str, float]) -> list[list[str]]:
    """The keys from the highest score down; keys with equal scores share a group."""
    return [sorted(k for k in scores if scores[k] == s) for s in sorted(set(scores.values()),
                                                                         reverse=True)]


def ranks(values: list[float]) -> list[float]:
    """Rank 1 for the smallest value; tied values share the mean of their ranks: the values below,
    plus the middle of the run of ties."""
    return [sum(x < v for x in values) + (values.count(v) + 1) / 2 for v in values]


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation of the ranks; None when one side is constant."""
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx, syy = sum((a - mx) ** 2 for a in rx), sum((b - my) ** 2 for b in ry)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else None
