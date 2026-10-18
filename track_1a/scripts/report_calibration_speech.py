"""The speech meaning judge beside chrF: per dialect and over all, the clips the judge calls
unrelated against those with chrF below speech_eval's threshold, and the dialects ranked by each.
The hallucinated flag's minimum word count is not applied, since scores.json keeps no output text.
"""
from __future__ import annotations

from collections import Counter
from statistics import mean

from redteam import paths
from redteam.calibration import crossed_bootstrap, interval, spearman, worst_first
from redteam.review import cohen_kappa
from redteam.speech_eval import HALLUCINATION_CHRF
from redteam.speech_finding import RATED

SPEECH = paths.SHIPPED / "speech" / "20261017-141121" / "scores.json"
ALL = "all"  # the key of the numbers over every language or dialect


def rounded(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def agreement_table(found: dict) -> dict:
    """The 2x2 table of (unrelated, low chrF) and Cohen's kappa, with an interval for kappa from
    resampling dialects and sentences apart; draws where kappa is undefined are left out."""
    cells, kappa = Counter(found.values()), cohen_kappa(list(found.values()))
    return {"n": len(found), "both": cells[True, True], "judge_only": cells[True, False],
            "chrf_only": cells[False, True], "neither": cells[False, False],
            "raw": rounded((cells[True, True] + cells[False, False]) / len(found)),
            "kappa": rounded(kappa), "kappa_ci95": interval(crossed_bootstrap(found, cohen_kappa))}


def speech_agreement(clips, threshold: float = HALLUCINATION_CHRF) -> dict:
    """Per dialect and over all, the meaning judge's unrelated against chrF below threshold."""
    found = {(c["dialect"], c["sentence_id"]): (c["meaning"] == "unrelated", c["chrf"] < threshold)
             for c in clips if c.get("meaning") in RATED}
    dialects = sorted({d for d, _ in found})
    return {ALL: agreement_table(found), "per_dialect": {
        d: agreement_table({k: v for k, v in found.items() if k[0] == d}) for d in dialects}}


def ranking(clips, threshold: float = HALLUCINATION_CHRF) -> dict:
    """The dialects from worst to best by the judge's unrelated share and by chrF alone, ties in
    one group, and the Spearman correlation of each chrF measure with the judge's share."""
    rated = [c for c in clips if c.get("meaning") in RATED]
    unrelated, low_chrf, mean_chrf = {}, {}, {}
    for d in sorted({c["dialect"] for c in rated}):
        rows = [c for c in rated if c["dialect"] == d]
        unrelated[d] = mean(float(c["meaning"] == "unrelated") for c in rows)
        low_chrf[d] = mean(float(c["chrf"] < threshold) for c in rows)
        mean_chrf[d] = mean(c["chrf"] for c in rows)
    deficit = {d: -x for d, x in mean_chrf.items()}  # so that higher is worse for all three
    judge = list(unrelated.values())
    return {"per_dialect": {d: {"unrelated": rounded(unrelated[d]), "mean_chrf": round(x, 2),
                                "low_chrf": rounded(low_chrf[d])} for d, x in mean_chrf.items()},
            "by_unrelated": worst_first(unrelated), "by_low_chrf": worst_first(low_chrf),
            "by_mean_chrf": worst_first(deficit),
            "spearman_low_chrf": rounded(spearman(judge, list(low_chrf.values()))),
            "spearman_mean_chrf": rounded(spearman(judge, list(deficit.values())))}


def speech(scores: dict) -> dict:
    return {"run": scores["run_id"], "file": str(SPEECH.relative_to(paths.ROOT)),
            "judge": scores["judge"], "chrf_below": HALLUCINATION_CHRF,
            **{name: {"model": scores[key], "agreement": speech_agreement(scores[name]),
                      "ranking": ranking(scores[name])}
               for name, key in (("apertus", "model"), ("whisper", "whisper_model"))}}
