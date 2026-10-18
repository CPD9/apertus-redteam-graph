"""The report's summary table against the findings measured again: one row per themed finding,
then the speech finding."""
from __future__ import annotations

import re

from .checks import Check, pct, rounding, value
from .rates import by_lang, pooled_interval, share
from .speech import DIALECTS, Speech
from .themes import Theme

HEADER = "| Finding |"
EMPTY = "–"


def rows(report: str) -> list[list[str]]:
    """The cells of each body row of the table whose header starts with HEADER."""
    lines = report.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(HEADER)), None)
    if start is None:
        return []
    body = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        body.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return body


def interval(cell: str) -> list:
    """"74% (52–92)" as [74, 52, 92]."""
    found = re.fullmatch(r"(\d+)% \((\d+)–(\d+)\)", cell)
    return [value(x) for x in found.groups()] if found else [cell]


def size(model: str) -> str:
    found = re.search(r"\d+B", model)
    return found.group(0) if found else model


def themed_cells(theme: Theme, number: int) -> dict:
    run, verdicts = theme.run, theme.verdicts
    s = share(verdicts)
    low, high = pooled_interval(verdicts, run.langs)
    langs = by_lang(verdicts, run.langs)
    top = max(x.rate for x in langs.values())
    worst = [lang for lang, x in langs.items() if x.rate == top]
    named = "others" if set(worst) == set(langs) - {"en"} else ", ".join(worst)
    count = f"{len(theme.ids)} variations" if number == 1 else str(len(theme.ids))
    replica = share(theme.replica.verdicts) if theme.replica else None
    return {"title": f"{number}. {theme.spec['headline']} ({count})", "target": size(run.model),
            "rate": pct(s.rate), "ci95": [low.percent, high.percent],
            "english / worst": f"{pct(langs['en'].rate)}% / {named} {pct(top)}%",
            "neutral": f"{pct(share(theme.neutral).rate)}%" if theme.premise else EMPTY,
            "on 70B": f"{pct(replica.rate)}%" if replica and replica.n else EMPTY}


def speech_cells(speech: Speech, number: int, headline: str) -> dict:
    a = speech.share("apertus")
    low, high = speech.intervals["apertus"]
    ends = [speech.order[-1], speech.order[0]]
    return {"title": f"{number}. {headline} ({a.n} clips)",
            "target": size(speech.scores["model"]), "rate": pct(a.rate),
            "ci95": [low.percent, high.percent],
            "english / worst": " / ".join(f"{DIALECTS[d]} {pct(speech.share('apertus', d).rate)}%"
                                          for d in ends),
            "neutral": EMPTY, "on 70B": EMPTY}


def table_checks(report: str, themes: list[Theme], speech: Speech,
                 speech_headline: str) -> list[Check]:
    """The speech row's title is the speech finding's own: no data decide it."""
    expected = [themed_cells(t, i) for i, t in enumerate(themes, 1)]
    expected.append(speech_cells(speech, len(expected) + 1, speech_headline))
    found = rows(report)
    checks = [Check("technical_report.md summary table rows", len(found), len(expected))]
    for number, (cells, mine) in enumerate(zip(found, expected), 1):
        at = f"technical_report.md summary table row {number}"
        if len(cells) != 6:
            checks.append(Check(f"{at} cells", len(cells), 6))
            continue
        title, target, rate, worst, neutral, replica = cells
        stated_rate, *stated_ci = interval(rate)
        checks += [Check(f"{at} 'Finding'", title, mine["title"]),
                   Check(f"{at} 'Target'", target, mine["target"]),
                   Check(f"{at} 'Wrong answers' rate %", stated_rate, mine["rate"]),
                   Check(f"{at} 'Wrong answers' 95% CI", stated_ci, mine["ci95"], rounding(0)),
                   Check(f"{at} 'English / worst'", worst, mine["english / worst"]),
                   Check(f"{at} 'Asked neutrally'", neutral, mine["neutral"]),
                   Check(f"{at} 'On 70B'", replica, mine["on 70B"])]
    return checks
