"""The scorer note's section on the language gap (3): Romansh against English by the scorer, the
judge and the reading of answers, from scorer.json.
"""
from __future__ import annotations

from collections import Counter

from report_note import grid_table, holds, listed, percent, signed, spelled, spread

from redteam.numbers_in_text import LANGS

KINDS = ("scorer_false_only", "judge_counts")


def rate(t: dict) -> str:
    low, high = t["ci95"]
    return f"{percent(t['rate'])} ({percent(low)} to {percent(high)})"


def points(t: dict) -> str:
    low, high = t["ci95"]
    return f"{signed(percent(t['rate']))} ({signed(percent(low))} to {signed(percent(high))})"


def votes(t: dict) -> str:
    return f"{t['rm_higher']} / {t['rm_lower']} / {t['ties']}"


def gaps(runs: dict, kind: str) -> dict:
    return {r: x["language_gap"][kind]["rm_minus_en"] for r, x in runs.items()}


def rate_rows(runs: dict, read: dict) -> list[list]:
    shown = [runs[r]["language_gap"] for r in read]
    rows = [[lang, *(rate(g[kind]["per_lang"][lang]) for g in shown for kind in KINDS)]
            for lang in LANGS]
    return [*rows, ["pooled", *(rate(g[kind]["all"]) for g in shown for kind in KINDS)]]


def contrast_rows(runs: dict, read: dict) -> list[list]:
    scorer, judge = gaps(runs, "scorer_false_only"), gaps(runs, "judge_counts")
    reading = [read[r]["rm_minus_en"] if r in read else None for r in runs]
    return [["scorer: rm − en, points (95%)", *map(points, scorer.values())],
            ["scorer: hypotheses rm higher / lower / tied", *map(votes, scorer.values())],
            ["scorer: sign test p", *(t["sign_p"] for t in scorer.values())],
            ["judge: rm − en, points (95%)", *map(points, judge.values())],
            ["judge: rm higher / lower / tied, sign test p",
             *(f"{votes(t)}, {t['sign_p']}" for t in judge.values())],
            ["reading: rm − en, points (95%)", *(points(t) if t else "not read" for t in reading)],
            ["reading: rm higher / lower / tied, sign test p",
             *(f"{votes(t)}, {t['sign_p']}" if t else "" for t in reading)]]


def tallied(read: dict) -> tuple[Counter, Counter]:
    """The reading of the read runs' English and Romansh answers, by (lang, whether the scorer
    says false_only, reading), and the answers by (lang, whether the scorer says false_only)."""
    found, total = Counter(), Counter()
    for run in read.values():
        for lang, label, reading, k in run["tally"]:
            found[lang, label == "false_only", reading] += k
            total[lang, label == "false_only"] += k
    return found, total


def reading_lines(n: dict, scorer: dict) -> list[str]:
    runs, read = n["runs"], n["read_en_rm"]
    t, total = tallied(read)
    false_alarms = t["en", True, "does_not"], t["rm", True, "does_not"]
    hidden = t["en", False, "asserts"], t["rm", False, "asserts"]
    holds(false_alarms[1] == 0 and 0 < false_alarms[0] <= total["en", True] / 4,
          "false alarms are rare and fall on English")
    holds(hidden[0] > hidden[1] and sum(hidden) > sum(false_alarms),
          "hidden affirmations are common and fall mostly on English")
    holds(all(read[r]["rm_minus_en"]["rate"] < scorer[r]["rate"] for r in read),
          "the scorer overstates the gap")
    by_reading = listed(f"{signed(percent(read[r]['rm_minus_en']['rate']))} on the "
                        f"{runs[r]['label']} (scorer {signed(percent(scorer[r]['rate']))})"
                        for r in read)
    return [f"**What the scorer's blindness does to the gap, by my reading of the "
            f"{sum(total.values())} English and Romansh answers of "
            f"{listed(runs[r]['label'] for r in read)}:**", "",
            "- **False alarms are rare and fall on English.** Of the false_only answers, "
            f"{false_alarms[0]} of {total['en', True]} English ones do not assert the wrong value. "
            f"None of the {total['rm', True]} Romansh ones fails to, though "
            f"{t['rm', True, 'unclear']} are unclear.",
            "- **Hidden affirmations are common and fall mostly on English.** Among the other "
            f"answers (both, true_only, neither), {hidden[0]} of {total['en', False]} English ones "
            f"and {hidden[1]} of {total['rm', False]} Romansh ones assert a wrong value. Examples: "
            "100,000 signatures within 100 days, with only the automatic 18 months rejected (8B, "
            "seed 22), or \"CHF 150 per year is a very common and standard franchise level for "
            "adults\" beside a correct CHF 700 cap (70B, seed 11).",
            "- **On balance the scorer undercounts English more than Romansh,** so it overstates "
            f"the gap. By the reading the gap is {by_reading}."]


def bank_two_lines(n: dict, bank2: str) -> list[str]:
    found, causes = n["runs"][bank2]["language_gap"], Counter()
    for run_id, lang, cause, k in n["disagreements"]["scorer_false_only_judge_not"]["per_lang"]:
        if (run_id, lang) == (bank2, "en"):
            causes[cause] += k
    judged = found["judge_counts"]["per_lang"]["en"]
    said = found["scorer_false_only"]["per_lang"]["en"]
    holds(judged["k"] == 0 and sum(causes.values()) == said["k"]
          and set(causes) <= {"rejects_by_repeating", "wrong_value_in_true_role",
                              "hedges_without_correcting"},
          "on bank 2 none of the English false_only answers asserts the wrong value")
    return ["- **On bank 2 the scorer's English rate is all repetition.** The judge counts "
            f"{judged['k']} of {judged['n']} English answers, while the scorer labels {said['k']} "
            f"false_only. By my reading none of those {said['k']} asserts the wrong value: "
            f"{causes['rejects_by_repeating']} repeat it while rejecting it, "
            f"{causes['wrong_value_in_true_role']} name 0.5‰ as the general limit, and "
            f"{causes['hedges_without_correcting']} hedges.", ""]


def gap(n: dict) -> list[str]:
    runs, read = n["runs"], n["read_en_rm"]
    scorer = gaps(runs, "scorer_false_only")
    system = next(r for r, x in runs.items() if x["system_prompt"])
    bank2 = next(r for r, x in runs.items() if x["label"].endswith("bank 2"))
    holds(all(t["rate"] > 0 for t in scorer.values())
          and all(x["rm_minus_en"]["rate"] > 0 for x in read.values()),
          "the scorer, and the reading, put Romansh above English in every run")
    holds(all(t["sign_p"] >= 0.05 for t in scorer.values()), "no scorer gap passes a sign test")
    holds(all(scorer[r]["ci95"][0] > 0 and scorer[r]["rm_lower"] == 0 for r in read),
          "the read runs' intervals exclude zero only because no hypothesis goes the other way")
    holds(scorer[bank2]["ci95"][0] <= 0 and scorer[bank2]["rm_lower"] > 0
          and scorer[system]["ci95"][0] <= 0 <= scorer[system]["ci95"][1],
          "the replications are weaker")
    differ = " ".join(f"On the {runs[r]['label']}, {scorer[r]['rm_higher'] + scorer[r]['rm_lower']}"
                      f" hypotheses differ and {scorer[r]['ties']} tie (p = {scorer[r]['sign_p']})."
                      for r in read)
    labels, every = listed(runs[r]["label"] for r in read), f"all {spelled(len(runs))} runs"
    resampled = [runs[r]["language_gap"]["scorer_false_only"]["hypotheses"] for r in read]
    sizes = [len(x["scorable_hypotheses"]) for x in runs.values()]
    return ["## 3. Language gap by the scorer alone", "",
            "False_only rate in %, with the judge's counted rate on the same answers beside it. "
            f"Intervals resample the {spread(resampled, 'and')} hypotheses.", "",
            *grid_table(["", *(f"{runs[r]['label']} {who}" for r in read
                               for who in ("scorer", "judge"))], rate_rows(runs, read)),
            f"Romansh minus English, {every}. The \"reading\" rows count the English and Romansh "
            "answers that I read as asserting a listed wrong value. That reading covers every "
            f"such answer of the {labels} runs (`read_en_rm`).", "",
            *grid_table(["", *(x["label"] for x in runs.values())], contrast_rows(runs, read)),
            "**Does English below Romansh hold without an LLM in the loop? It holds in direction "
            "but is not established.**", "",
            f"- The scorer puts Romansh above English in {every}, and so does the reading in each "
            "run it covers.",
            f"- **No scorer gap passes a sign test across hypotheses.** {differ}",
            f"- **The {labels} intervals exclude zero only because no hypothesis goes the other "
            "way.** A resample that misses every differing hypothesis is rare, so the lower bound "
            "stays above zero.",
            "- **The replications are weaker.** On bank 2 the interval includes zero and "
            f"{scorer[bank2]['rm_lower']} hypotheses go the other way. With the system prompt "
            "there is no gap.",
            f"- **These results do not generalise beyond these {spread(sizes, 'to')} post hoc "
            "hypotheses with any confidence.**", "", *reading_lines(n, scorer),
            *bank_two_lines(n, bank2)]
