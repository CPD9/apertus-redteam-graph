"""A recomputed bootstrap bound and the stated values it admits. On a grid small enough to
enumerate, the bound is the exact quantile, and a stated bound agrees when the harness's 2000
draws give it with fair chance. Elsewhere it is drawn again with another random stream, and a
stated bound agrees within CI of it."""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import sqrt

from .exact import Spread

CI = 0.03  # how far a bound drawn with another random stream may move, as a share
HARNESS_DRAWS = 2000  # the draws behind every bootstrap interval the report and findings state
# 2000 draws put a 2.5% bound where the chance at or below it is 2.5% give or take a standard
# error of sqrt(0.025 x 0.975 / 2000); three of them leave little room for chance.
SLACK = 3 * sqrt(0.025 * 0.975 / HARNESS_DRAWS)


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
