"""Shares of counted answers and their 95% intervals: Wilson's for one share, Newcombe's for the
difference of two, and cluster bootstraps where answers share a prompt or a language. A bootstrap
on a small grid is enumerated exactly; a larger one is drawn at random."""
from __future__ import annotations

import random
from dataclasses import dataclass
from functools import lru_cache
from math import sqrt

from .bounds import Bound
from .exact import layout, spread

Z = 1.96
# Ten times the harness's draws, so the cross-check's own sampling error stays small next to
# the tolerance on the grids too large to enumerate.
DRAWS = 20000
# Deliberately not the harness's seed: an interval that agrees within the tolerance from another
# random stream does not hinge on one sequence of draws.
SEED = 18


@dataclass(frozen=True)
class Share:
    k: int
    n: int

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def wilson(self) -> tuple[float, float]:
        return wilson(self.k, self.n)


def share(verdicts) -> Share:
    verdicts = list(verdicts)
    return Share(sum(v.counted for v in verdicts), len(verdicts))


def by_lang(verdicts, langs: list[str]) -> dict[str, Share]:
    return {lang: share(v for v in verdicts if v.lang == lang) for lang in langs}


def wilson(k: int, n: int) -> tuple[float, float]:
    if not n:
        return 0.0, 1.0
    p = k / n
    centre = p + Z * Z / (2 * n)
    spread = Z * sqrt(p * (1 - p) / n + Z * Z / (4 * n * n))
    scale = 1 + Z * Z / n
    return max(0.0, (centre - spread) / scale), min(1.0, (centre + spread) / scale)


def newcombe(first: Share, second: Share) -> tuple[float, float]:
    """Newcombe's hybrid score interval for first.rate - second.rate."""
    (low1, high1), (low2, high2) = first.wilson, second.wilson
    p1, p2 = first.rate, second.rate
    return (p1 - p2 - sqrt((p1 - low1) ** 2 + (high2 - p2) ** 2),
            p1 - p2 + sqrt((high1 - p1) ** 2 + (p2 - low2) ** 2))


def quantile(values: list[float], q: float) -> float:
    """Linear interpolation between the order statistics around q."""
    ordered = sorted(values)
    at = q * (len(ordered) - 1)
    low = int(at)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (at - low)


def multiplicities(rng: random.Random, items: list) -> dict:
    """How often each item is picked in len(items) draws with replacement."""
    picked = {}
    for _ in items:
        item = items[rng.randrange(len(items))]
        picked[item] = picked.get(item, 0) + 1
    return picked


def two_way(values: dict[tuple, float], draws: int = DRAWS,
            seed: int = SEED) -> tuple[Bound, Bound]:
    """95% interval of the mean of cells keyed by two kinds of cluster (hypothesis and language,
    or dialect and sentence): each resample draws both kinds, and a cell weighs as often as its
    row and its column were drawn."""
    items = tuple(sorted(values.items()))
    enumerated = spread(items)
    if enumerated:
        return Bound.exact(enumerated, 0.025), Bound.exact(enumerated, 0.975)
    return tuple(map(Bound.drawn, drawn(items, draws, seed)))


@lru_cache(maxsize=None)
def drawn(items: tuple, draws: int, seed: int) -> tuple[float, float]:
    rows, cols, cells = layout(items)
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        row_n, col_n = [0] * len(rows), [0] * len(cols)
        for _ in rows:
            row_n[rng.randrange(len(rows))] += 1
        for _ in cols:
            col_n[rng.randrange(len(cols))] += 1
        weights = [(row_n[r] * col_n[c], value) for r, c, value in cells]
        total = sum(w for w, _ in weights)
        if total:  # a draw of only rows and columns whose shared cells are missing has no mean
            means.append(sum(w * value for w, value in weights) / total)
    return quantile(means, 0.025), quantile(means, 0.975)


def cells(verdicts, langs: list[str]) -> dict[tuple[str, str], float]:
    """The counted share of each hypothesis in each language it was asked in."""
    grid: dict[tuple[str, str], list[bool]] = {}
    for v in verdicts:
        if v.lang in langs:
            grid.setdefault((v.hypothesis, v.lang), []).append(v.counted)
    return {cell: sum(flags) / len(flags) for cell, flags in grid.items()}


def pooled_interval(verdicts, langs: list[str]) -> tuple[Bound, Bound]:
    """The pooled share's interval over hypotheses and languages, never narrower than Wilson's:
    with few cells, or equal cells, the resamples barely vary."""
    verdicts = list(verdicts)
    low, high = two_way(cells(verdicts, langs))
    floor_low, floor_high = share(verdicts).wilson
    return low.no_higher_than(floor_low), high.no_lower_than(floor_high)


def paired_difference(premise, neutral, langs: list[str]) -> tuple[Bound, Bound]:
    """Interval of premise minus neutral share over the cells asked both ways, paired by
    hypothesis and language, never narrower than Newcombe's."""
    with_premise, without = cells(premise, langs), cells(neutral, langs)
    paired = {cell: with_premise[cell] - without[cell] for cell in with_premise if cell in without}
    low, high = two_way(paired)
    floor_low, floor_high = newcombe(share(v for v in premise if (v.hypothesis, v.lang) in paired),
                                     share(v for v in neutral if (v.hypothesis, v.lang) in paired))
    return low.no_higher_than(floor_low), high.no_lower_than(floor_high)


def hypothesis_draws(size: int, draws: int = DRAWS, seed: int = SEED) -> list[dict[int, int]]:
    """Resamples of hypotheses by index, shared by every rate that is compared."""
    rng = random.Random(seed)
    return [multiplicities(rng, list(range(size))) for _ in range(draws)]


def resampled(table: list[tuple[int, int]], weights: dict[int, int]) -> float:
    """The pooled rate of (counted, answers) per hypothesis in one resample."""
    return (sum(w * table[i][0] for i, w in weights.items())
            / sum(w * table[i][1] for i, w in weights.items()))
