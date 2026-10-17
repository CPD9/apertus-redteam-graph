"""95% intervals for rates pooled over the variations of a themed finding.

The answers of a finding are not independent: the answers to one variation share a prompt, and
those in one language share how well Apertus knows it. So a pooled rate's interval resamples
variations and languages, not answers (stats.cluster_bootstrap over the counted share of each
variation in each language), as the speech finding resamples speakers and sentences. The rate of a
single variation keeps its Wilson interval.
"""
from __future__ import annotations

from math import sqrt

from .answers import Answer, of, per_lang, share
from .stats import DRAWS, SEED, cluster_bootstrap

METHOD = {"pooled": "two-way cluster bootstrap over variations and languages, never narrower "
                    "than the Wilson interval",
          "premise_minus_neutral": "the same bootstrap of the difference, paired by variation "
                                   "and language, never narrower than Newcombe's interval",
          "per_variation": "Wilson", "draws": DRAWS, "seed": SEED}


def cells(answers: list[Answer], langs: list[str]) -> dict[tuple[str, str], float]:
    """The counted share of each variation in each language it was asked in. Each cell holds one
    answer per seed, so the mean of the cells is the pooled rate."""
    shares = {}
    for hypothesis in dict.fromkeys(a.hypothesis for a in answers):
        for lang, s in per_lang(of(answers, {hypothesis}), langs).items():
            if s.n:
                shares[hypothesis, lang] = s.rate
    return shares


def rounded(ci: tuple[float, float]) -> list[float]:
    return [round(x, 3) for x in ci]


def interval(answers: list[Answer], langs: list[str]) -> list[float]:
    """The pooled rate's 95% interval, rounded as findings keep it. Answers that share a prompt add
    uncertainty, never remove it, so the interval is widened to Wilson's where that is wider: with
    few cells the draws vary too little, and not at all when every cell gives the same share."""
    low, high = cluster_bootstrap(cells(answers, langs))
    wilson_low, wilson_high = share(answers).ci95
    return rounded((min(low, wilson_low), max(high, wilson_high)))


def brief(answers: list[Answer], langs: list[str]) -> dict:
    """Share.brief() of answers pooled over variations, with the clustered interval."""
    return {**share(answers).brief(), "ci95": interval(answers, langs)}


def explained(variations: int, langs: int) -> str:
    """How the notes of a finding state the method."""
    said = ("Pooled 95% CIs resample variations and languages, as answers sharing either are not "
            f"independent ({DRAWS} draws, seed {SEED}; never narrower than Wilson's).")
    if variations == 1:
        return (f"{said} With one variation, they resample only the {langs} languages and still "
                "understate the uncertainty.")
    if variations == 2:
        return (f"{said} With two variations, they rest mostly on the {langs} languages and still "
                "understate the uncertainty.")
    return said


def newcombe(premise: list[Answer], neutral: list[Answer]) -> tuple[float, float]:
    """Newcombe's hybrid score interval for the premise share minus the neutral share, built from
    the Wilson interval of each."""
    first, second = share(premise), share(neutral)
    (low1, high1), (low2, high2) = first.ci95, second.ci95
    p1, p2 = first.rate, second.rate
    low = p1 - p2 - sqrt((p1 - low1) ** 2 + (high2 - p2) ** 2)
    high = p1 - p2 + sqrt((high1 - p1) ** 2 + (p2 - low2) ** 2)
    return low, high


def within(answers: list[Answer], kept: dict[tuple[str, str], float]) -> list[Answer]:
    return [a for a in answers if (a.hypothesis, a.lang) in kept]


def difference(premise: list[Answer], neutral: list[Answer], langs: list[str]) -> list[float]:
    """95% interval of how much more often answers state the error with the false premise than
    without it, paired cell by cell: the same variation in the same language, asked both ways.
    Cells asked only one way are left out. As in interval(), the draws cannot vary when every cell
    differs by the same amount, so the interval is widened to Newcombe's where that is wider."""
    with_premise, without = cells(premise, langs), cells(neutral, langs)
    paired = {cell: with_premise[cell] - without[cell] for cell in with_premise if cell in without}
    low, high = cluster_bootstrap(paired)
    floor_low, floor_high = newcombe(within(premise, paired), within(neutral, paired))
    return rounded((min(low, floor_low), max(high, floor_high)))
