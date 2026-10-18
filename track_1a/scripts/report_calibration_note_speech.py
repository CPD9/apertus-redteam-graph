"""The calibration note's section 3: the speech meaning judge against chrF below a threshold, per
dialect, and how the dialects rank under each.
"""
from __future__ import annotations

from decimal import Decimal

from report_calibration_speech import ALL
from report_note import grid_table, holds, listed, percent, rounded, span, spelled, two

from redteam.speech_eval import MIN_FLUENT_WORDS
from redteam.speech_finding import DIALECTS


def number(x: float) -> str:
    return str(int(x)) if x == int(x) else str(x)


def overlap(intervals) -> bool:
    return all(a[0] <= b[1] and b[0] <= a[1] for a in intervals for b in intervals)


def flat(groups: list[list[str]]) -> list[str]:
    return [d for group in groups for d in group]


def ordered(groups: list[list[str]]) -> str:
    return ", ".join(" = ".join(group) for group in groups)


def tie(group: list[str], below_counts: dict, ranks: dict, clips: int, below: str) -> str:
    means = [Decimal(str(ranks["per_dialect"][d]["mean_chrf"])) for d in group]
    return (f"{listed(group)} tie at {below_counts[group[0]]} of {clips} below {below}, and their "
            f"mean chrF differs by {max(means) - min(means)}.")


def agreement_rows(name: str, agreement: dict, dialects: list[str], interval: bool) -> list[list]:
    cells = [agreement["per_dialect"][d] for d in dialects] + [agreement[ALL]]
    rows = [[f"{name} κ", *(two(t["kappa"]) for t in cells)]]
    if interval:
        rows.append(["95%", *(span(t["kappa_ci95"]) for t in cells)])
    return [*rows, [f"{name} raw agreement", *(f"{percent(t['raw'], stored=3)}%" for t in cells)]]


def ranking_lines(apertus: dict, whisper: dict, below: str) -> list[str]:
    ranks, per_dialect = apertus["ranking"], apertus["agreement"]["per_dialect"]
    judge, low, mean = (flat(ranks[k]) for k in ("by_unrelated", "by_low_chrf", "by_mean_chrf"))
    holds(set(judge[:3]) == set(low[:3]) == set(mean[:3])
          and set(judge[-3:]) == set(low[-3:]) == set(mean[-3:]),
          "chrF keeps the judge's worst three and best three")
    holds(all(abs(judge.index(d) - order.index(d)) <= 1 for d in judge for order in (low, mean)),
          "chrF reproduces the judge's order up to adjacent swaps")
    holds(judge[0] != low[0] and low[0] == mean[0], "the single worst dialect changes under chrF")
    unrelated = {d: t["both"] + t["judge_only"] for d, t in per_dialect.items()}
    lexical = {d: t["both"] + t["chrf_only"] for d, t in per_dialect.items()}
    clips, chrf = per_dialect[judge[0]]["n"], ranks["per_dialect"]
    apart = lexical[low[0]] - lexical[judge[0]]
    ties = [tie(g, lexical, ranks, clips, below) for g in ranks["by_low_chrf"] if len(g) > 1]
    whispered = [t["both"] + t["judge_only"] for t in whisper["agreement"]["per_dialect"].values()]
    rows = [["judge's unrelated share", ordered(ranks["by_unrelated"]), "–"],
            [f"share with chrF below {below}", ordered(ranks["by_low_chrf"]),
             two(ranks["spearman_low_chrf"])],
            ["mean chrF", ordered(ranks["by_mean_chrf"]), two(ranks["spearman_mean_chrf"])]]
    return ["**Dialect ranking under chrF alone.** For Apertus, worst first (= marks a tie):", "",
            *grid_table(["measure", "ranking", "Spearman with the judge"], rows),
            "chrF alone reproduces the judge's order up to adjacent swaps. It keeps the same worst "
            f"three ({', '.join(judge[:3])}) and best three ({', '.join(judge[-3:])}). The single "
            f"worst dialect changes, though. Under the judge it is {DIALECTS[judge[0]]}, with "
            f"{unrelated[judge[0]]} of {clips} clips unrelated against {DIALECTS[low[0]]}'s "
            f"{unrelated[low[0]]}. Under chrF it is {DIALECTS[low[0]]}, {spelled(apart)} "
            f"clip{'s' * (apart != 1)} apart ({lexical[low[0]]} against {lexical[judge[0]]} below "
            f"{below}; mean chrF {rounded(chrf[low[0]]['mean_chrf'], 1)} against "
            f"{rounded(chrf[judge[0]]['mean_chrf'], 1)}). So a \"worst dialect\" label is not "
            f"robust, but the worst-three group is. {' '.join(ties)} Whisper has {min(whispered)} "
            f"to {max(whispered)} unrelated clips per dialect, so its ranking is noise (Spearman "
            f"{two(whisper['ranking']['spearman_low_chrf'])} and "
            f"{two(whisper['ranking']['spearman_mean_chrf'])}).", ""]


def speech(s: dict) -> list[str]:
    apertus, whisper, below = s["apertus"], s["whisper"], number(s["chrf_below"])
    dialects = list(apertus["agreement"]["per_dialect"])
    sizes = {t["n"] for model in (apertus, whisper)
             for t in model["agreement"]["per_dialect"].values()}
    holds(len(sizes) == 1, "every dialect has the same sentences")
    a, w = apertus["agreement"], whisper["agreement"]
    holds(overlap([t["kappa_ci95"] for t in a["per_dialect"].values()]),
          "the per-dialect intervals all overlap")
    holds(w[ALL]["both"] == 0 and abs(w[ALL]["kappa"]) < 0.05, "for Whisper no clip is both")
    return ["## 3. Speech: meaning judge against chrF", "",
            f"Run {s['run']} has {a[ALL]['n']} clips per model: the same {min(sizes)} sentences in "
            f"each of {len(dialects)} dialects, one speaker each. The lexical signal is chrF below "
            f"{below} (`speech_eval.HALLUCINATION_CHRF`). The run's hallucinated flag also needs "
            f"at least {MIN_FLUENT_WORDS} words, but scores.json keeps no output text, so only the "
            "chrF half is applied. Per-dialect κ intervals resample sentences. The overall "
            "interval resamples dialects and sentences apart.", "",
            *grid_table(["", *dialects, ALL],
                        [*agreement_rows("Apertus", a, dialects, True),
                         *agreement_rows("Whisper", w, dialects, False)]),
            f"**Apertus.** Over all clips, {a[ALL]['both']} are both unrelated and below chrF "
            f"{below}, {a[ALL]['judge_only']} are only unrelated, {a[ALL]['chrf_only']} only below "
            f"{below} and {a[ALL]['neither']} neither. The finding is the overall κ of "
            f"{two(a[ALL]['kappa'])} ({span(a[ALL]['kappa_ci95'])}). The per-dialect intervals all "
            f"overlap, so at {min(sizes)} clips the dialects cannot be told apart.", "",
            f"**Whisper.** The judge calls {w[ALL]['both'] + w[ALL]['judge_only']} clips "
            f"unrelated, {w[ALL]['both'] + w[ALL]['chrf_only']} clips have chrF below {below}, and "
            "no clip is both. So κ is about 0, or undefined (–) where both measures are constant. "
            "The high raw agreement only says that both see almost no failures.", "",
            *ranking_lines(apertus, whisper, below),
            "Limits:", "",
            "- **Shared reference.** chrF and the judge compare with the same SwissDial sentence, "
            "so their agreement is not independent evidence.",
            f"- **Fixed threshold.** The threshold of {below} comes from speech_eval and was not "
            "tuned here.",
            "- **Confounding.** There is one speaker per dialect, so dialect and speaker cannot be "
            "told apart.", ""]
