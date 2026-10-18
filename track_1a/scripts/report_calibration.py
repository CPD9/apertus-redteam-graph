"""The judge's count (Answer.confirmed) against the numeric scorer's decisive labels, the counted
wrong-answer rates corrected for it, and the speech meaning judge beside chrF.

false_only asserts the error and true_only does not; both and neither give no reference label.
A run's corrected rate applies its Se and Sp, pooled over languages, to its counted rate over
every hypothesis. Speech sets "unrelated" against chrF below speech_eval's threshold, without the
hallucinated flag's minimum word count, since scores.json keeps no output text.

    cd track_1a && python3 scripts/report_calibration.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # without pip install -e

import report_scorer as rs  # noqa: E402

from redteam import answers, paths  # noqa: E402
from redteam.cache import CACHE_DIR  # noqa: E402
from redteam.calibration import (DRAWS, SEED, Cluster, Confusion, accuracy,  # noqa: E402
                                 bootstrap, clip, confusion, crossed_bootstrap, estimate,
                                 interval, spearman, worst_first)
from redteam.numbers_in_text import LANGS  # noqa: E402
from redteam.review import cohen_kappa  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402
from redteam.speech_eval import HALLUCINATION_CHRF  # noqa: E402
from redteam.speech_finding import RATED  # noqa: E402

REFERENCE = {"false_only": True, "true_only": False}
# Here true_only does not mean correct: the answer can give the true deductible and still affirm
# that cost sharing has no cap (docs/audit/scorer.md), so a second reading leaves it out.
UNSURE = ("kvg_deductible_range",)
SPEECH = paths.SHIPPED / "speech" / "20261017-141121" / "scores.json"
COMPARED = ("20261016-172309-1f71", "20261017-140533-a21a")  # 8B and 70B, one bank, one judge
ALL = "all"


def labelled(items, left_out=()) -> list:
    return [i for i in items if i.score.label in REFERENCE and i.answer.hypothesis not in left_out]


def pairs(items) -> list[tuple[bool, bool]]:
    return [(i.answer.confirmed, REFERENCE[i.score.label]) for i in items]


def per_hypothesis(reference) -> dict[str, Confusion]:
    return {h: confusion(pairs([i for i in reference if i.answer.hypothesis == h]))
            for h in sorted({i.answer.hypothesis for i in reference})}


def accuracy_by_lang(reference) -> dict:
    """Se and Sp over all languages and per language, each resampling its own hypotheses."""
    per_lang = {lang: [i for i in reference if i.answer.lang == lang] for lang in LANGS}
    return {ALL: accuracy(list(per_hypothesis(reference).values())), "per_lang": {
        lang: accuracy(list(per_hypothesis(chosen).values())) for lang, chosen in per_lang.items()}}


def misses(reference) -> dict:
    """The false_only answers the judge does not count, by whether it flagged them at all."""
    missed = [i.answer for i in reference if REFERENCE[i.score.label] and not i.answer.confirmed]
    return {"n": len(missed), "not_flagged": sum(not a.flagged for a in missed),
            "flagged_without_severity": sum(a.flagged for a in missed)}


def strata(answer_list, reference, lang: str) -> list[list[Cluster]]:
    """A cluster per hypothesis: its answers in lang (in every language for ALL), and the judge's
    confusion on its labelled answers in every language. Hypotheses with labels come first."""
    confusions, with_labels, without = per_hypothesis(reference), [], []
    for h in dict.fromkeys(a.hypothesis for a in answer_list):
        chosen = [a for a in answer_list if a.hypothesis == h and lang in (ALL, a.lang)]
        cluster = Cluster(sum(a.confirmed for a in chosen), len(chosen),
                          confusions.get(h, Confusion()))
        if h in confusions:
            with_labels.append(cluster)
        else:
            without.append(cluster)
    return [with_labels, without]


def rounded(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def summary(point, draws) -> dict:
    """Raw and corrected rate with intervals, the corrected one clipped to [0, 1] and unclipped.
    Draws where the correction is void are counted and left out of its intervals."""
    fixed = [p for _, p in draws if p is not None]
    return {"raw": rounded(point[0]), "raw_ci95": interval([q for q, _ in draws]),
            "corrected": rounded(clip(point[1])),
            "corrected_ci95": interval([clip(p) for p in fixed]),
            "unclipped": rounded(point[1]), "unclipped_ci95": interval(fixed),
            "void_draws": len(draws) - len(fixed)}


def difference(before, after) -> dict:
    """after minus before from paired estimates (the point, then the bootstrap draws). Corrected
    rates are subtracted unclipped, since a difference of clipped rates measures the clipping."""
    (q0, p0), (q1, p1) = before[0], after[0]
    raw = [a[0] - b[0] for a, b in zip(after[1], before[1])]
    fixed = [a[1] - b[1] for a, b in zip(after[1], before[1]) if None not in (a[1], b[1])]
    return {"raw": rounded(q1 - q0), "raw_ci95": interval(raw),
            "unclipped": None if None in (p0, p1) else rounded(p1 - p0),
            "unclipped_ci95": interval(fixed), "void_draws": len(raw) - len(fixed)}


def corrected_rates(answer_list, reference) -> dict:
    """Raw and corrected rate over all languages and per language, and Romansh minus English.
    Every language has the same strata, so the bootstrap draws pair up across languages."""
    split = {lang: strata(answer_list, reference, lang) for lang in (ALL, *LANGS)}
    found = {lang: (estimate([c for stratum in s for c in stratum]), bootstrap(s))
             for lang, s in split.items()}
    return {ALL: summary(*found[ALL]),
            "per_lang": {lang: summary(*found[lang]) for lang in LANGS},
            "rm_minus_en": difference(found["en"], found["rm"]),
            "hypotheses_with_and_without_labels": [len(s) for s in split[ALL]]}


def reference_numbers(answer_list, reference) -> dict:
    return {"labelled": len(reference),
            "asserts": sum(REFERENCE[i.score.label] for i in reference),
            "hypotheses": len({i.answer.hypothesis for i in reference}),
            "accuracy": accuracy_by_lang(reference),
            "corrected": corrected_rates(answer_list, reference)}


def run_numbers(run, items) -> dict:
    reference = labelled(items)
    return {"model": run.model, "judge": run.judge, "answers": len(run.answers),
            "scored_by_label": dict(sorted(Counter(i.score.label for i in items).items())),
            "misses": misses(reference),
            "per_hypothesis": {h: asdict(c) for h, c in per_hypothesis(reference).items()},
            "reference": reference_numbers(run.answers, reference),
            "without_unsure": reference_numbers(run.answers, labelled(items, UNSURE))}


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
    return {"run": scores["run_id"], "file": str(SPEECH.relative_to(rs.TRACK)),
            "judge": scores["judge"], "chrf_below": HALLUCINATION_CHRF,
            **{name: {"model": scores[key], "agreement": speech_agreement(scores[name]),
                      "ranking": ranking(scores[name])}
               for name, key in (("apertus", "model"), ("whisper", "whisper_model"))}}


def numbers() -> dict:
    hypotheses, facts = {h["id"]: h for h in load_hypotheses()}, rs.facts_table()
    out = {"script": "scripts/report_calibration.py", "scorer": "scripts/report_scorer.py",
           "reference": "scorer false_only = asserts the error, true_only = does not",
           "bootstrap": {"draws": DRAWS, "seed": SEED, "resampled": "hypotheses (for corrected "
                         "rates, with and without labels apart); speech: dialects and sentences"},
           "unsure": list(UNSURE), "runs": {}}
    every = []
    for run_id in COMPARED:
        run = answers.load_run(paths.SHIPPED / run_id, hypotheses, CACHE_DIR)
        items = rs.scored(run_id, run.answers, facts)
        every += labelled(items)
        out["runs"][run_id] = {"label": rs.RUNS[run_id], **run_numbers(run, items)}
    out["both_runs_accuracy"] = accuracy_by_lang(every)  # a hypothesis pools both runs' answers
    out["speech"] = speech(json.loads(SPEECH.read_text()))
    return out


def main():
    rs.OUT.mkdir(parents=True, exist_ok=True)
    (rs.OUT / "calibration.json").write_text(json.dumps(numbers(), indent=1) + "\n")


if __name__ == "__main__":
    main()
