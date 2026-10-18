"""How far people agree with the judge and with each other, and what their labels say about the
judge's counts. The set is balanced on the judge's verdict, so raw agreement and kappa describe
the set, not the runs.

The labels are few, about 30 a run and two or three per language and verdict, so every figure
comes with a 95% interval. Raw agreement has Wilson's. Kappa's resamples hypotheses, since the
judge's errors gather in a few of them (calibration.py); where every pair agrees it is [1, 1], and
Wilson's says more. The corrected rate of a language is a stratified estimate: for each judge
verdict, the share of its labelled answers that people say assert the error, weighted by the
run's answers with that verdict. That equals Rogan-Gladen with the language's own Se and Sp, so no
language borrows another's. The intervals of these rates and of Se and Sp draw each stratum's
share from Beta(k + 1/2, n - k + 1/2), Jeffreys' interval, and take the strata as independent:
resampling three labels that agree would give the same share in every draw.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from itertools import combinations

from .calibration import DRAWS, SEED, Confusion, interval, resamples, sensitivity, specificity
from .stats import wilson


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def kappa(cells: Counter) -> float | None:
    """Cohen's kappa from the counts of (first says yes, second says yes); None when undefined:
    no pairs, or both gave one constant label (expected agreement 1)."""
    n = sum(cells.values())
    if not n:
        return None
    observed = (cells[True, True] + cells[False, False]) / n
    pa = (cells[True, True] + cells[True, False]) / n
    pb = (cells[True, True] + cells[False, True]) / n
    expected = pa * pb + (1 - pa) * (1 - pb)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def cohen_kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    return kappa(Counter((bool(a), bool(b)) for a, b in pairs))


def share(pairs: list[tuple]) -> dict:
    """How many pairs agree, with Wilson's interval for the share."""
    n, agree = len(pairs), sum(p[0] == p[1] for p in pairs)
    return {"n": n, "agree": agree, "raw_agreement": _round(agree / n) if n else None,
            "ci95": [round(x, 3) for x in wilson(agree, n)] if n else None}


def tally(triples: list[tuple], draws: int = DRAWS, seed: int = SEED) -> dict:
    """share() and kappa of (first, second, hypothesis) triples; kappa's interval resamples the
    hypotheses."""
    clusters = defaultdict(Counter)
    for a, b, hyp in triples:
        clusters[hyp][bool(a), bool(b)] += 1
    clusters = list(clusters.values())
    drawn = []
    for (weights,) in resamples([len(clusters)], draws, seed) if clusters else []:
        cells = Counter()
        for i, w in weights.items():
            cells.update({cell: w * k for cell, k in clusters[i].items()})
        drawn.append(kappa(cells))
    return {**share(triples), "kappa": _round(kappa(sum(clusters, Counter()))),
            "kappa_ci95": interval([x for x in drawn if x is not None])}


def judge_pairs(rows: list[dict]) -> list[tuple]:
    """(judge, human, hypothesis) for the rows with a yes or no; "can't tell" has neither."""
    return [(r["judge_violation"], r["human_violation"], r.get("hypothesis")) for r in rows
            if None not in (r["judge_violation"], r["human_violation"])]


def grouped(rows: list[dict], key: str) -> dict:
    return {k: tally(judge_pairs([r for r in rows if r[key] == k]))
            for k in dict.fromkeys(r[key] for r in rows)}


def hedged_as_no(rows: list[dict]) -> list[dict]:
    """The labels under the judge's own rule, which counts no hedged answer."""
    return [{**r, "human_violation": r["human_violation"] and not r["hedged"]} for r in rows]


def between_people(rows: list[dict], key: str, with_kappa: bool = True) -> list[dict]:
    """Every pair of labellers, on the items both of them labelled."""
    by_person = defaultdict(dict)
    for r in rows:
        by_person[r["labeller"]][r["id"]] = (r[key], r["hypothesis"])
    out = []
    for a, b in combinations(sorted(by_person), 2):
        shared = sorted(by_person[a].keys() & by_person[b].keys())
        triples = [(by_person[a][i][0], *by_person[b][i]) for i in shared]
        if triples:
            out.append({"labellers": [a, b], **(tally(triples) if with_kappa else share(triples))})
    return out


def stratum_shares(rows: list[dict]) -> dict[tuple, list[float]]:
    """Per (language, judge verdict), each labelled answer's share of people saying it asserts the
    error, so an answer two people labelled counts once."""
    votes = defaultdict(list)
    for r in rows:
        votes[r["lang"], r["judge_violation"], r["id"]].append(r["human_violation"])
    strata = defaultdict(list)
    for (lang, counted, _), said in votes.items():
        strata[lang, counted].append(sum(said) / len(said))
    return strata


def corrected(shares: dict, population: Counter, langs: set) -> float | None:
    """The share of the answers in langs people would say assert the error; None when a stratum
    with answers has no label."""
    cells = {cell: n for cell, n in population.items() if cell[0] in langs and n}
    if not cells or any(cell not in shares for cell in cells):
        return None
    return sum(n * shares[cell] for cell, n in cells.items()) / sum(cells.values())


def se_sp(shares: dict, population: Counter) -> tuple[float | None, float | None]:
    if any(cell not in shares for cell, n in population.items() if n):
        return None, None
    c = sum((Confusion(tp=n * shares[lang, True], fp=n * (1 - shares[lang, True])) if counted
             else Confusion(fn=n * shares[lang, False], tn=n * (1 - shares[lang, False]))
             for (lang, counted), n in population.items() if n), Confusion())
    return sensitivity(c), specificity(c)


def counted_rate(population: Counter, langs: set) -> float | None:
    total = sum(n for (lang, _), n in population.items() if lang in langs)
    counted = sum(n for (lang, c), n in population.items() if lang in langs and c)
    return _round(counted / total) if total else None


def _estimate(point: float | None, drawn: list[float | None]) -> dict:
    """The estimate and its interval. A Beta draw is never exactly 0 or 1, so where all labels
    agree the interval is stretched to the estimate, as Brown, Cai and DasGupta do for k = n."""
    ci = None if point is None else interval([x for x in drawn if x is not None])
    if ci:
        ci = [min(ci[0], _round(point)), max(ci[1], _round(point))]
    return {"estimate": _round(point), "ci95": ci}


def accuracy(rows: list[dict], population: Counter, draws: int = DRAWS,
             seed: int = SEED) -> dict:
    """What one run's decided labels say about its judge. population: the run's answers per
    (language, judge verdict). Se and Sp weight each stratum by its answers; the corrected rates
    of a language use only its own labels."""
    strata = stratum_shares(rows)
    point = {cell: sum(s) / len(s) for cell, s in strata.items()}
    rng = random.Random(seed)
    drawn = [{cell: rng.betavariate(sum(s) + 0.5, len(s) - sum(s) + 0.5)
              for cell, s in strata.items()} for _ in range(draws)]
    langs = list(dict.fromkeys(lang for lang, _ in population))
    se, sp = se_sp(point, population)
    drawn_se_sp = [se_sp(d, population) for d in drawn] if se is not None else []
    rates = {}
    for lang, group in [*((lang, {lang}) for lang in langs), ("all", set(langs))]:
        estimate = corrected(point, population, group)
        spread = [] if estimate is None else [corrected(d, population, group) for d in drawn]
        rates[lang] = {"counted": counted_rate(population, group),
                       "corrected": _estimate(estimate, spread)}
    return {"labelled": {lang: {"counted": len(strata.get((lang, True), [])),
                                "not_counted": len(strata.get((lang, False), []))}
                         for lang in langs},
            "missing": [f"{lang} {'counted' if c else 'not counted'}"
                        for (lang, c), n in population.items() if n and (lang, c) not in strata],
            "sensitivity": _estimate(se, [x for x, _ in drawn_se_sp]),
            "specificity": _estimate(sp, [x for _, x in drawn_se_sp]), "rates": rates}


def judge_accuracy(rows: list[dict], population: Counter) -> dict:
    """accuracy() under the codebook's rule, which counts a hedged wrong value, and under the
    judge's."""
    decided = [r for r in rows if r["human_violation"] is not None]
    return {"codebook": accuracy(decided, population),
            "hedged_as_no": accuracy(hedged_as_no(decided), population)}
