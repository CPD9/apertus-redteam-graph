"""The numbers a themed finding's texts state (title, overview, observed behaviour, breadth and
notes) against the theme measured again."""
from __future__ import annotations

import re

from .checks import Check, flat, pct, present, rounding, stated
from .rates import by_lang, paired_difference, pooled_interval, share
from .themes import BAR, Theme, breadth, over_bar

READINGS = {"clearly more likely": lambda low, high: low > 0,
            "even when nobody suggests a wrong one": lambda low, high: high < 0,
            "within chance": lambda low, high: low <= 0 <= high}


def numbers(text: str, pattern: str) -> list[int]:
    """The comma-separated whole numbers after a lead-in, or none when the text lacks it."""
    match = re.search(pattern, flat(text))
    return [int(x) for x in match.group(1).split(", ")] if match else []


def listed(text: str, pattern: str) -> list[str]:
    """The comma-separated items after a lead-in, or none when the text lacks it."""
    match = re.search(pattern, flat(text))
    return match.group(1).split(", ") if match else []


def percents(text: str, pattern: str) -> dict[str, int]:
    """"name 50%, other 58%" after a lead-in, as {name: 50, other: 58}."""
    found = re.search(pattern, flat(text))
    pairs = re.findall(r"(\S+) (\d+)%", found.group(1)) if found else []
    return {name: int(number) for name, number in pairs}


def overview(at: str, text: str, theme: Theme) -> list[Check]:
    run, verdicts = theme.run, theme.verdicts
    s = share(verdicts)
    low, high = pooled_interval(verdicts, run.langs)
    checks = [
        *stated(at, text, r"Measured on (\S+): (\d+) of (\d+) verified answers \((\d+)%",
                {"model": run.model, "k": s.k, "n": s.n, "rate %": pct(s.rate)}),
        *stated(at, text, r"verified answers \(\d+%, 95% CI (\d+)%-(\d+)%\)",
                {"ci95 low %": low.percent, "ci95 high %": high.percent}, rounding(0)),
        *stated(at, text, r"from (\d+) variations? asked in (\d+) languages with (\d+) sampling",
                {"variations": len(theme.ids), "languages": len(run.langs),
                 "seeds": len(run.seeds)}),
        Check(f"{at} by language %", percents(text, r"By language: ([^.]*)\."),
              {lang: pct(x.rate) for lang, x in by_lang(verdicts, run.langs).items()}),
    ]
    return checks + control(at, text, theme) + replica(at, text, theme)


def control(at: str, text: str, theme: Theme) -> list[Check]:
    if not theme.premise:
        return [present(at, text, "Asked neutral questions", False)]
    langs = theme.run.langs
    neutral, premise = share(theme.neutral), share(theme.premise)
    low, high = pooled_interval(theme.neutral, langs)
    checks = [*stated(at, text, r"it erred in (\d+)% of answers .{0,40}against (\d+)% with it",
                      {"neutral %": pct(neutral.rate), "premise %": pct(premise.rate)}),
              *stated(at, text, r"it erred in \d+% of answers \(95% CI (\d+)%-(\d+)%\)",
                      {"neutral ci95 low %": low.percent, "neutral ci95 high %": high.percent},
                      rounding(0))]
    if theme.spec.get("control_caveat"):
        return checks + [present(at, text, theme.spec["control_caveat"], True,
                                 "the control caveat of themes.json")]
    low, high = paired_difference(theme.verdicts, theme.neutral, langs)
    checks += stated(at, text, r"premise minus neutral: ([+−-]?\d+) to ([+−-]?\d+) points",
                     {"gap low points": low.percent, "gap high points": high.percent},
                     rounding(0))
    return checks + [present(at, text, phrase, holds(low.value, high.value))
                     for phrase, holds in READINGS.items()]


def replica(at: str, text: str, theme: Theme) -> list[Check]:
    r = theme.replica
    if r is None or not r.measured:
        return [present(at, text, "as target,", False)]
    s = share(r.verdicts)
    failed = re.search(r"(\d+) could not be measured", flat(text))
    return [*stated(at, text, r"With (\S+) as target, (\d+) of (\d+) variations? reproduced",
                    {"replica model": r.run.model, "replica reproduced": len(r.reproduced),
                     "replica measured": len(r.measured)}),
            Check(f"{at} replica failed", int(failed.group(1)) if failed else 0, len(r.failed)),
            *stated(at, text, r"variations? reproduced[^;]*; (\d+) of (\d+) verified answers "
                    r"\((\d+)%\)", {"replica k": s.k, "replica n": s.n,
                                    "replica %": pct(s.rate)})]


def breadth_text(at: str, text: str, theme: Theme) -> list[Check]:
    hit = over_bar(theme)
    checks = [*stated(at, text, r"(\d+) variations? reproduced; pooled, the counted rate reaches "
                      r"the harness's bar \((\d+)% of answers\) in (\d+) of (\d+) languages",
                      {"variations": len(theme.ids), "bar %": pct(BAR),
                       "languages over bar": len(hit), "languages": len(theme.run.langs)}),
              Check(f"{at} languages over bar", listed(text, r"languages: ([a-z, ]+)\."), hit)]
    r = theme.replica
    if r and r.measured:
        checks += stated(at, text, r"as target, (\d+) of (\d+) variations? reproduced\.",
                         {"replica reproduced": len(r.reproduced),
                          "replica measured": len(r.measured)})
    return checks


def notes(at: str, text: str, theme: Theme, refs: dict[str, dict]) -> list[Check]:
    unrated = re.search(r"The judge rated (\d+) more flagged answers 0", flat(text))
    sourced = sum(bool(refs[h].get("sources")) for h in theme.ids)
    cited = re.search(r"\((\d+) of (\d+) cite sources\)", flat(text))
    if cited:
        stated_sources = [int(cited.group(1)), int(cited.group(2))]
    else:
        everyone = "a sourced reference" in text
        stated_sources = [len(theme.ids) if everyone else 0, len(theme.ids)]
    return [
        Check(f"{at} flagged answers rated 0", int(unrated.group(1)) if unrated else 0,
              theme.unrated()),
        Check(f"{at} references citing sources", stated_sources, [sourced, len(theme.ids)]),
        Check(f"{at} left out under the bar",
              listed(text, r"reproduced only with those answers counted: ([^.]+)\."),
              theme.dropped),
        Check(f"{at} left out after reading",
              re.findall(r"Left out after reading the answers: (\S+), as", flat(text)),
              theme.excluded),
        Check(f"{at} seeds", numbers(text, r"seeds \[([\d, ]+)\]"), theme.run.seeds),
        Check(f"{at} variations %", percents(text, r"Variations?: (.*)\.$"),
              {h: pct(share(theme.run.of({h})).rate) for h in theme.ids}),
    ]


def text_checks(name: str, finding: dict, theme: Theme, refs: dict[str, dict]) -> list[Check]:
    at = f"findings/{name}.json"
    summary = finding["issue_summary"]
    s = share(theme.verdicts)
    return [
        Check(f"{at} issue_title", finding["issue_title"],
              theme.spec["title"].format(subjects=theme.subjects)),
        *overview(f"{at} issue_summary.overview", summary["overview"], theme),
        *stated(f"{at} issue_summary.observed_behavior", summary["observed_behavior"],
                r"(\d+) of (\d+) verified answers", {"k": s.k, "n": s.n}, at_start=True),
        Check(f"{at} issue_summary.self_assessed_breadth", summary["self_assessed_breadth"],
              str(breadth(theme))),
        *breadth_text(f"{at} issue_summary.self_assessed_breadth_justification",
                      summary["self_assessed_breadth_justification"], theme),
        *notes(f"{at} notes", finding["notes"], theme, refs),
    ]
