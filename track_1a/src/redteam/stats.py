import random
from collections import Counter
from math import sqrt

DRAWS, SEED = 2000, 1  # of every cluster bootstrap, fixed so a rebuild gives the same interval


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for k successes in n trials. Behaves well at small n and k=0/n."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def cluster_bootstrap(values: dict[tuple[str, str], float], draws: int = DRAWS,
                      seed: int = SEED) -> tuple[float, float]:
    """95% interval for the mean of values crossed by two kinds of cluster, e.g. clips keyed by
    (dialect, sentence): one speaker's clips are not independent, and neither are the recordings
    of one sentence. Each draw resamples both kinds with replacement and averages every cell of the
    drawn pairs, counted as often as its pair was drawn. The seed is fixed, so rerunning a report
    does not move the interval."""
    rows = sorted({a for a, _ in values})
    cols = sorted({b for _, b in values})
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        row_weight = Counter(rng.choices(rows, k=len(rows)))
        col_weight = Counter(rng.choices(cols, k=len(cols)))
        total = weight = 0
        for (a, b), value in values.items():
            w = row_weight[a] * col_weight[b]
            total, weight = total + w * value, weight + w
        if weight:  # with gaps in the grid a draw can miss every cell
            means.append(total / weight)
    means.sort()
    return means[round(0.025 * (len(means) - 1))], means[round(0.975 * (len(means) - 1))]
