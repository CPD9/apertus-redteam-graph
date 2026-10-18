"""Numbers in the report's running text outside the finding paragraphs: the abstract, the method,
the comparison of 8B and 70B, the figure captions, the limitations and the reproducibility notes.
Each sentence is found by a pattern; a reworded sentence is reported, not skipped."""
from __future__ import annotations

import re

from .audit import Audit
from .checks import Check, flat, pct, present, rounding, stated
from .rates import share
from .themes import reproduced

R = "technical_report.md"
LANGS = {"English": "en", "German": "de", "Swiss German": "gsw", "French": "fr", "Italian": "it",
         "Romansh": "rm"}


def rate(c, key: str, arm: int) -> int:
    return pct(c.pooled(key, arm)["rate"])


def theme_rates(audit: Audit, theme_id: str) -> tuple[int, int]:
    theme = audit.themes[theme_id]
    return pct(share(theme.verdicts).rate), pct(share(theme.neutral).rate)


def abstract(text: str, audit: Audit) -> list[Check]:
    at, size = f"{R} abstract", audit.size
    civic, civic_neutral = theme_rates(audit, "civic_sycophancy")
    either_way = all(share(audit.themes[t].neutral).rate >= share(audit.themes[t].premise).rate
                     for t in ("safety_knowledge_gaps", "pension_rules"))
    return [
        *stated(at, text, r"Asked about (\d+) Swiss topics", {"topics": len(size.done)}),
        *stated(at, text, r"Apertus 70B answers wrongly in (\d+)% of English and (\d+)% of Romansh "
                r"answers \(8B: (\d+)% and (\d+)%\)",
                {"70B en %": rate(size, "en", 1), "70B rm %": rate(size, "rm", 1),
                 "8B en %": rate(size, "en", 0), "8B rm %": rate(size, "rm", 0)}),
        *stated(at, text, r"the 8B agrees with the false claim in (\d+)% of answers, although "
                r"asked neutrally it gets the same facts wrong in only (\d+)%",
                {"civic premise %": civic, "civic neutral %": civic_neutral}),
        present(at, text, "pensions it is wrong either way", either_way,
                "'pensions it is wrong either way' (checked: for safety and pensions the neutral "
                "share is at least the premise share)"),
        *stated(at, text, r"audio input turns (\d+)% of Swiss German clips into sentences nobody "
                r"said; a Swiss German Whisper does so for (\d+)%",
                {"apertus %": pct(audit.speech.share("apertus").rate),
                 "whisper %": pct(audit.speech.share("whisper").rate)}),
    ]


def method(text: str, audit: Audit) -> list[Check]:
    at, banks = f"{R} method", audit.banks
    canonical, target70 = audit.runs["canonical"], audit.runs["target70"]
    mitigation = audit.runs["mitigation"]
    flagged = canonical.ended("finding")
    sourced = sum(bool(h.get("sources")) for name in ("bank", "bank2") for h in banks[name])
    return [
        *stated(at, text, r"We wrote (\d+) hypotheses, each with a reference answer: bank 1 "
                r"\((\d+)\) and (\d+) seed probes, run on the 8B and the 70B, and bank 2 \((\d+)\)",
                {"hypotheses": sum(map(len, banks.values())), "bank 1": len(banks["bank"]),
                 "seed probes": len(banks["core"]), "bank 2": len(banks["bank2"])}),
        *stated(at, text, r"The (\d+) references of the two banks are written from cited sources",
                {"references with sources": sourced}),
        *stated(at, text, r"three sampling seeds \((\d+) answers\)",
                {"answers per hypothesis": len(canonical.langs) * len(canonical.seeds)}),
        *stated(at, text, r"\((\d+) answers in the 8B run, (\d+) in the 70B run\)",
                {"8B answers": len(canonical.verdicts), "70B answers": len(target70.verdicts)}),
        *stated(at, text, r"(\d+) of the (\d+) flagged on the 8B are reproduced",
                {"reproduced": sum(reproduced(canonical, h) for h in flagged),
                 "flagged": len(flagged)}),
        *stated(at, text, r"repeats the (\d+) hypotheses flagged on the 70B \((\d+) measured\)",
                {"70B flagged": len(target70.ended("finding")),
                 "measured": len(mitigation.logged_n)}),
        Check(f"{at} mitigation run asks the 70B's flagged hypotheses",
              sorted(target70.ended("finding")), sorted(mitigation.hypotheses)),
    ]


def significant(c) -> list[str]:
    return [key for key, drawn in c.intervals.items()
            if key != "all" and (drawn["change"][1].value < 0 or drawn["change"][0].value > 0)]


def tally(c, arm: int, strategy: str) -> int:
    """Compared hypotheses whose last attack in one run used this strategy."""
    return sum(c.runs[arm].last_attack.get(h) == strategy for h in c.done)


def sizes(text: str, audit: Audit) -> list[Check]:
    at, c = f"{R} findings dataset", audit.size
    small, large = c.runs
    langs = [k for k in c.tables if k != "all"]
    ends = all(min(langs, key=lambda k: c.pooled(k, arm)["rate"]) == "en"
               and max(langs, key=lambda k: c.pooled(k, arm)["rate"]) == "rm" for arm in (0, 1))
    low, high = c.intervals["all"]["change"]
    rm_low, rm_high = c.intervals["rm"]["change"]
    named = flat(text).partition("significant only in ")[2].partition(", and smallest")[0]
    said = [LANGS.get(name, name) for name in named.replace(" and ", ", ").split(", ")]
    smallest = re.search(r"and smallest in ([A-Z][a-z]+(?: [A-Z][a-z]+)?) \(", flat(text))
    return [
        *stated(at, text, r"Across the (\d+) hypotheses with results on both models \((\w+) of "
                r"the (\d+) failed on the 70B\)", {"compared": len(c.done),
                                                   "failed on 70B": len(large.ended("error")),
                                                   "attacked": len(small.hypotheses)}),
        present(at, text, "lowest in English and highest in Romansh on both", ends),
        *stated(at, text, r"(\d+)% to (\d+)% on the 8B and (\d+)% to (\d+)% on the 70B \((\d+) "
                r"answers per cell; the (\w+) hypotheses the 70B was never broken on",
                {"8B en %": rate(c, "en", 0), "8B rm %": rate(c, "rm", 0),
                 "70B en %": rate(c, "en", 1), "70B rm %": rate(c, "rm", 1),
                 "answers per cell": c.pooled("en", 0)["n"],
                 "never broken on 70B": sum(large.outcome.get(h) == "no_issue" for h in c.done)}),
        *stated(at, text, r"a false premise for (\d+) of the (\d+) on the 8B and (\d+) on the 70B",
                {"8B false premise": tally(c, 0, "false_premise"), "compared": len(c.done),
                 "70B false premise": tally(c, 1, "false_premise")}),
        *stated(at, text, r"permits or origin \((\w+) on the 8B, (\w+) on the 70B\)",
                {"8B practical need": tally(c, 0, "practical_need"),
                 "70B practical need": tally(c, 1, "practical_need")}),
        *stated(at, text, r"for the (\w+) the 70B was never broken on, a question mixing",
                {"70B code switch": tally(c, 1, "code_switch")}),
        *stated(at, text, r"\((\d+)% vs (\d+)% overall, difference ([−+-]?\d+) points",
                {"8B all %": rate(c, "all", 0), "70B all %": rate(c, "all", 1),
                 "change points": pct(c.change("all"))}),
        *stated(at, text, r"difference [−+-]?\d+ points, 95% CI ([−+-]?\d+) to ([−+-]?\d+)\)",
                {"change ci95 low": low.percent, "change ci95 high": high.percent}, rounding(0)),
        Check(f"{at} languages where the change is significant", said, significant(c)),
        *stated(at, text, r"smallest in Romansh \(([−+-]?\d+) points",
                {"rm change points": pct(c.change("rm"))}),
        *stated(at, text, r"smallest in Romansh \([−+-]?\d+ points, 95% CI ([−+-]?\d+) to "
                r"([+−-]?\d+)\)", {"rm ci95 low": rm_low.percent, "rm ci95 high": rm_high.percent},
                rounding(0)),
        Check(f"{at} language with the smallest gain",
              LANGS.get(smallest.group(1)) if smallest else None, max(langs, key=c.change)),
        *stated(at, text, r"pools their (\d+) answers each",
                {"answers per variation": len(small.langs) * len(small.seeds)}),
    ]


def captions(text: str, audit: Audit, premise_rows: int) -> list[Check]:
    at, speech = f"{R} figure captions", audit.speech
    (a_low, a_high), (w_low, w_high) = speech.intervals["apertus"], speech.intervals["whisper"]
    return [
        *stated(at, text, r"Premise versus neutral question for the (\d+) reproduced hypotheses",
                {"figure 2 rows": premise_rows}),
        *stated(at, text, r"All dialects: (\d+)% \(95% CI \d+–\d+\) against (\d+)%",
                {"apertus %": pct(speech.share("apertus").rate),
                 "whisper %": pct(speech.share("whisper").rate)}),
        *stated(at, text, r"All dialects: \d+% \(95% CI (\d+)–(\d+)\) against \d+% "
                r"\((\d+)–(\d+)\)",
                {"apertus ci95 low": a_low.percent, "apertus ci95 high": a_high.percent,
                 "whisper ci95 low": w_low.percent, "whisper ci95 high": w_high.percent},
                rounding(0)),
    ]


def closing(text: str, audit: Audit) -> list[Check]:
    c, canonical = audit.size, audit.runs["canonical"]
    before, after = c.runs
    differ = sum(before.prompts.get(h) != after.prompts.get(h) for h in c.done)
    return [
        *stated(f"{R} limitations", text, r"(\d+) of the (\d+) hypotheses compared across sizes "
                r"end with different prompts", {"different prompts": differ,
                                                "compared": len(c.done)}),
        *stated(f"{R} reproducibility", text, r"replays run `([\w-]+)`",
                {"canonical run": canonical.id}),
        *stated(f"{R} reproducibility", text, r"seeds (\d+), (\d+) and (\d+) at temperature",
                {f"seed {i + 1}": seed for i, seed in enumerate(canonical.seeds)}),
    ]
