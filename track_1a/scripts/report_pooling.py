"""Wrong-answer rates pooled across hypotheses, from a table of (wrong, total) per hypothesis.

The answers to one hypothesis share a prompt, so they are not independent of each other. Pooled
rates therefore get their interval from resampling whole hypotheses rather than from the count
of answers, which would make the interval far too narrow.
"""
from __future__ import annotations

import random
from collections import Counter

DRAWS = 4000


def resamples(size):
    rng = random.Random(1)  # fixed, so rebuilding the figures does not move the intervals
    return [Counter(rng.choices(range(size), k=size)) for _ in range(DRAWS)]


def rate(table, weights):
    return (sum(w * table[i][0] for i, w in weights.items())
            / sum(w * table[i][1] for i, w in weights.items()))


def interval(values):
    values = sorted(values)
    return [round(values[round(q * (len(values) - 1))], 4) for q in (0.025, 0.975)]


def totals(table):
    return sum(c[0] for c in table), sum(c[1] for c in table)


def pooled(table, draws):
    k, n = totals(table)
    return {"k": k, "n": n, "rate": round(k / n, 4),
            "ci95": interval(rate(table, d) for d in draws)}


def difference(before, after, draws):
    """Change in the pooled rate from before to after, both resampled with the same hypotheses."""
    (k0, n0), (k1, n1) = totals(before), totals(after)
    return {"rate": round(k1 / n1 - k0 / n0, 4),
            "ci95": interval(rate(after, d) - rate(before, d) for d in draws)}
