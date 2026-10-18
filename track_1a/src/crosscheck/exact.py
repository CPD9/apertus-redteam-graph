"""The exact distribution of a two-way cluster bootstrap mean, on a grid small enough to list
every resample: each way of drawing the rows and the columns, weighed by its multinomial chance.
On such grids the means fall on a few values, so a bound drawn at random can land one value
away depending on the stream; the exact distribution says how likely each value is."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from functools import lru_cache
from math import comb, factorial

# Resamples of the rows times resamples of the columns: 4 hypotheses x 6 languages give
# 35 x 462. Larger grids are drawn at random instead.
LARGEST = 20000


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
