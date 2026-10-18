"""A recomputed bootstrap bound and the stated values it admits. On a grid small enough to list
every resample, the bound is the exact quantile of the two-way cluster bootstrap mean (each way of
drawing the rows and the columns, weighed by its multinomial chance), and a stated bound agrees
when the harness's 2000 draws give it with fair chance: on such grids the means fall on a few
values, so a bound drawn at random can land one value away depending on the stream. Elsewhere the
bound is drawn again with another random stream, and a stated bound agrees within CI of it."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
from functools import lru_cache
from math import comb, factorial, sqrt

# Resamples of the rows times resamples of the columns: 4 hypotheses x 6 languages give
# 35 x 462. Larger grids are drawn at random instead.
LARGEST = 20000
CI = 0.03  # how far a bound drawn with another random stream may move, as a share
HARNESS_DRAWS = 2000  # the draws behind every bootstrap interval the report and findings state
# 2000 draws put a 2.5% bound where the chance at or below it is 2.5% give or take a standard
# error of sqrt(0.025 x 0.975 / 2000); three of them leave little room for chance.
SLACK = 3 * sqrt(0.025 * 0.975 / HARNESS_DRAWS)


def compositions(draws: int, items: int):
    """Every way that draws picks with replacement can land on the items, as counts per item."""
    if items == 1:
        yield (draws,)
        return
    for first in range(draws, -1, -1):
        for rest in compositions(draws - first, items - 1):
            yield (first, *rest)


def chance(counts: tuple[int, ...]) -> float:
    """The multinomial chance of these counts when every pick is uniform over the items."""
    ways = factorial(sum(counts))
    for count in counts:
        ways //= factorial(count)
    return ways / len(counts) ** sum(counts)


def resamples(size: int) -> int:
    """How many different resamples of size items there are."""
    return comb(2 * size - 1, size)


@dataclass(frozen=True)
class Spread:
    means: tuple[float, ...]  # every mean a resample can give, ascending
    upto: tuple[float, ...]  # the chance of a mean at or below each

    def below(self, x: float) -> float:
        at = bisect_left(self.means, x)
        return self.upto[at - 1] if at else 0.0

    def at_most(self, x: float) -> float:
        at = bisect_right(self.means, x)
        return self.upto[at - 1] if at else 0.0

    def quantile(self, q: float) -> float:
        """The smallest mean with at least q of the chance at or below it: where the bound of a
        bootstrap settles as the draws grow."""
        return self.means[bisect_left(self.upto, q - 1e-12)]

    def estimates(self, q: float, slack: float) -> tuple[float, float]:
        """The lowest and the highest mean that a finite bootstrap gives with fair chance as its
        q bound: the means whose chance at or below them, or below them, comes within slack
        of q."""
        last = len(self.means) - 1
        return (self.means[min(bisect_left(self.upto, q - slack), last)],
                self.means[min(bisect_right(self.upto, q + slack), last)])


def layout(items: tuple) -> tuple[list, list, list[tuple[int, int, float]]]:
    """The rows, the columns and each cell as (row index, column index, value)."""
    rows = sorted({row for (row, _), _ in items})
    cols = sorted({col for (_, col), _ in items})
    return rows, cols, [(rows.index(row), cols.index(col), v) for (row, col), v in items]


@lru_cache(maxsize=None)
def spread(items: tuple) -> Spread | None:
    """The distribution of the mean of ((row, column), value) cells under the two-way bootstrap,
    or None when the grid has more than LARGEST resamples."""
    rows, cols, cells = layout(items)
    if resamples(len(rows)) * resamples(len(cols)) > LARGEST:
        return None
    row_draws = [(counts, chance(counts)) for counts in compositions(len(rows), len(rows))]
    mass: dict[float, float] = {}
    for col_counts in compositions(len(cols), len(cols)):
        col_chance = chance(col_counts)
        for row_counts, row_chance in row_draws:
            weight = total = 0
            for r, c, value in cells:
                w = row_counts[r] * col_counts[c]
                weight, total = weight + w, total + w * value
            if weight:  # a resample of only rows and columns whose shared cells are missing
                mean = round(total / weight, 12)  # one value however the sum was rounded
                mass[mean] = mass.get(mean, 0.0) + row_chance * col_chance
    found, running, upto = sum(mass.values()), 0.0, []
    for mean in sorted(mass):
        running += mass[mean]
        upto.append(running / found)
    return Spread(tuple(sorted(mass)), tuple(upto))


@dataclass(frozen=True)
class Bound:
    value: float
    lowest: float  # the lowest stated value admitted
    highest: float
    spread: Spread | None = None  # the exact distribution, when the grid was enumerated
    scale: float = 1.0  # 100 for a bound written as a percentage

    @classmethod
    def drawn(cls, value: float) -> Bound:
        return cls(value, value - CI, value + CI)

    @classmethod
    def exact(cls, spread: Spread, q: float) -> Bound:
        return cls(spread.quantile(q), *spread.estimates(q, SLACK), spread)

    def no_higher_than(self, floor: float) -> Bound:
        """A lower bound never above the Wilson or Newcombe one."""
        return replace(self, value=min(self.value, floor), lowest=min(self.lowest, floor),
                       highest=min(self.highest, floor))

    def no_lower_than(self, floor: float) -> Bound:
        return replace(self, value=max(self.value, floor), lowest=max(self.lowest, floor),
                       highest=max(self.highest, floor))

    @property
    def percent(self) -> Bound:
        return Bound(100 * self.value, 100 * self.lowest, 100 * self.highest, self.spread,
                     100 * self.scale)

    def admits(self, stated: float, tolerance: float) -> bool:
        return self.lowest - tolerance - 1e-9 <= stated <= self.highest + tolerance + 1e-9

    def position(self, stated: float, tolerance: float) -> list[float] | None:
        """Where a stated bound falls in the exact distribution: the chance of a mean below it
        and at or below it, give or take its rounding."""
        if self.spread is None:
            return None
        low, high = (stated - tolerance) / self.scale, (stated + tolerance) / self.scale
        return [round(self.spread.below(low), 4), round(self.spread.at_most(high), 4)]

    def text(self) -> str:
        if self.spread:
            how = f"exact; {HARNESS_DRAWS} draws give {self.lowest:.4g} to {self.highest:.4g}"
        else:
            how = f"redrawn; admits {self.lowest:.4g} to {self.highest:.4g}"
        return f"{self.value:.4g} ({how})"

    def record(self) -> dict:
        return {"value": round(self.value, 4),
                "admits": [round(self.lowest, 4), round(self.highest, 4)],
                "enumerated": self.spread is not None}
