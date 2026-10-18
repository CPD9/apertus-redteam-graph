"""The judge's count against the numeric scorer's label, and the language gap by either.

Items are scored answers as report_scorer builds them: item.answer is a replayed Answer and
item.score a redteam.scorer.Score. Answers to one hypothesis share a prompt, so every interval
comes from resampling hypotheses (report_pooling), and Romansh against English also gets an exact
sign test over hypotheses.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from report_pooling import difference, interval, pooled, resamples

from redteam.numbers_in_text import LANGS
from redteam.scorer import LABELS
from redteam.significance import sign_test


def says_false(item) -> bool:
    return item.score.label == "false_only"


def counted(item) -> bool:
    return item.answer.confirmed


def table(items) -> tuple[int, int, int, int]:
    """Judge and scorer both yes, judge only, scorer only, both no."""
    pairs = Counter((counted(i), says_false(i)) for i in items)
    return pairs[True, True], pairs[True, False], pairs[False, True], pairs[False, False]


def kappa_of(a: int, b: int, c: int, d: int) -> float | None:
    """Cohen's kappa of a table laid out as table() gives it; None where it is undefined."""
    n = a + b + c + d
    if n == 0:
        return None
    judge, scorer = (a + b) / n, (a + c) / n
    expected = judge * scorer + (1 - judge) * (1 - scorer)
    return None if expected == 1 else ((a + d) / n - expected) / (1 - expected)


def kappa(items) -> dict:
    """Kappa with an interval from resampling hypotheses; draws with no kappa drop out."""
    groups = defaultdict(list)
    for i in items:
        groups[i.answer.hypothesis].append(i)
    tables, whole = [table(g) for g in groups.values()], table(items)
    drawn = (kappa_of(*(sum(w * tables[h][c] for h, w in draw.items()) for c in range(4)))
             for draw in resamples(len(tables)))
    value = kappa_of(*whole)
    return {"n": len(items), "cells": whole, "kappa": None if value is None else round(value, 3),
            "ci95": interval(k for k in drawn if k is not None)}


def by_label(items) -> dict[str, dict]:
    """Answers with each scorer label, and how many of them the judge counts."""
    out = {}
    for label in LABELS:
        chosen = [i for i in items if i.score.label == label]
        out[label] = {"n": len(chosen), "counted": sum(map(counted, chosen))}
    return out


def agreement(items) -> dict:
    """The judge's count per scorer label, and kappa twice: with 'both' as the scorer's no, and
    with 'both' left out, since it holds corrections and confirmations alike."""
    return {"by_label": by_label(items), "both_as_no": kappa(items),
            "decided": kappa([i for i in items if i.score.label != "both"])}


def cells(items, hypotheses, langs, hit) -> list[tuple[int, int]]:
    """(hits, answers) of each hypothesis over the given languages."""
    out = []
    for h in hypotheses:
        chosen = [i for i in items if i.answer.hypothesis == h and i.answer.lang in langs]
        out.append((sum(map(hit, chosen)), len(chosen)))
    return out


def contrast(items, hit) -> dict:
    """Romansh minus English on the same resampled hypotheses, and a sign test over hypotheses."""
    hypotheses = sorted({i.answer.hypothesis for i in items})
    en, rm = (cells(items, hypotheses, [lang], hit) for lang in ("en", "rm"))
    test = sign_test([r / m - e / n for (e, n), (r, m) in zip(en, rm)])
    return {**difference(en, rm, resamples(len(hypotheses))), "rm_higher": test.first,
            "rm_lower": test.second, "ties": len(hypotheses) - test.first - test.second,
            "sign_p": round(test.p, 4)}


def gap(items, hit) -> dict:
    """The rate of hit per language and over all, pooled over hypotheses with an interval from
    resampling hypotheses, and Romansh against English."""
    hypotheses = sorted({i.answer.hypothesis for i in items})
    draws = resamples(len(hypotheses))
    return {"hypotheses": len(hypotheses),
            "all": pooled(cells(items, hypotheses, LANGS, hit), draws),
            "per_lang": {lang: pooled(cells(items, hypotheses, [lang], hit), draws)
                         for lang in LANGS},
            "rm_minus_en": contrast(items, hit)}
