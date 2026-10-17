"""The technical report's summary table, read off the findings files: one row per finding with
its pooled rate, English against the worst language, the neutral-question control and the 70B.
redteam.reproduce prints it once the findings match their rebuild.
"""
from __future__ import annotations

import re

from . import speech_finding
from .shares import Share
from .theme_finding import pct

HEADER = ("Finding", "Target", "Wrong answers (95% CI)", "English / worst", "Asked neutrally",
          "On 70B")
EMPTY = "–"


def counted(share: dict) -> str:
    return pct(share["k"] / share["n"])


def rate(value: float, ci95) -> str:
    return f"{pct(value)} ({pct(ci95[0])[:-1]}–{pct(ci95[1])[:-1]})"


def pooled(p: dict) -> Share:
    """The answers of all variations together, as the finding states them. The stated rate is
    rounded to three places (0.595 would print as 60% where the overview says 59%), so it is
    recounted from the variations, which must give it back. The interval, which resamples
    variations and languages, is printed as stated: the overview prints the same rounded values."""
    total = Share(*(sum(v[key] for v in p["harness_variations"]) for key in ("k", "n")))
    if total.brief()["rate"] != p["harness_overall_rate"]:
        raise ValueError(f"the variations of run {p['harness_run_id']} pool to {total.k} of "
                         f"{total.n}, not to the overall rate the finding states")
    return total


def themed_row(p: dict, first: bool) -> list[str]:
    variations, total = p["harness_variations"], pooled(p)
    by_lang = p["harness_reproduction_rates"]
    top = max(by_lang.values())
    worst = [lang for lang, r in by_lang.items() if r == top]
    named = "others" if set(worst) == set(by_lang) - {"en"} else ", ".join(worst)
    return [f"{len(variations)} variations" if first else str(len(variations)),
            rate(total.rate, p["harness_overall_ci95"]),
            f"{pct(by_lang['en'])} / {named} {pct(top)}",
            counted(p["harness_control"]["neutral"]) if "harness_control" in p else EMPTY,
            counted(p["harness_replication"]) if "harness_replication" in p else EMPTY]


def speech_row(p: dict) -> list[str]:
    counts = p["unrelated"]["all"]["apertus"]
    dialects = {d: s["apertus"] for d, s in p["unrelated"].items() if d != "all"}
    ends = (f(dialects, key=lambda d: (dialects[d]["rate"], d)) for f in (min, max))
    return [f"{counts['n']} clips",
            rate(counts["k"] / counts["n"], p["unrelated_cluster_ci95"]["apertus"]),
            " / ".join(f"{speech_finding.DIALECTS[d]} {counted(dialects[d])}" for d in ends),
            EMPTY, EMPTY]


def table(findings: list[dict]) -> str:
    """One row per finding in the order given; the first row names the unit of the count after
    each title."""
    lines = ["| " + " | ".join(HEADER) + " |", "|" + "---|" * len(HEADER)]
    for number, finding in enumerate(findings, 1):
        p = finding["model"]["parameters"]
        size = re.search(r"\d+B", finding["model"]["name"]).group(0)
        count, *cells = speech_row(p) if "unrelated" in p else themed_row(p, number == 1)
        title = f"{number}. {finding['issue_summary']['title']} ({count})"
        lines.append("| " + " | ".join([title, size, *cells]) + " |")
    return "\n".join(lines)
