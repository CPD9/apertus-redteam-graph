"""The speech finding and figure measured again from the per-clip scores: each clip's dialect,
sentence id, chrF and the judge's meaning label. The labels and chrF are taken as recorded (the
audio calls are not cached and SwissDial's text is not in the repository); every share, interval
and mean is recomputed from them."""
from __future__ import annotations

import re
from statistics import mean

from .checks import Check, pct, rounded, rounding, stated
from .rates import Share, two_way

DIALECTS = {"ag": "Aargau", "be": "Bern", "bs": "Basel", "gr": "Graubünden", "lu": "Lucerne",
            "sg": "St. Gallen", "vs": "Valais", "zh": "Zurich"}
RATED = ("same", "partial", "unrelated")
NAME = "(" + "|".join(map(re.escape, DIALECTS.values())) + ")"


def judged(clips: list[dict], verdict: str = "unrelated", dialect: str | None = None) -> Share:
    rated = [c for c in clips
             if c.get("meaning") in RATED and dialect in (None, c["dialect"])]
    return Share(sum(c["meaning"] == verdict for c in rated), len(rated))


def clustered(clips: list[dict]) -> tuple[float, float]:
    """Interval of the unrelated share resampling dialects (one speaker each) and sentences."""
    return two_way({(c["dialect"], c["sentence_id"]): float(c["meaning"] == "unrelated")
                    for c in clips if c.get("meaning") in RATED})


def by_dialect(clips: list[dict]) -> list[str]:
    """Dialects, the most often unrelated first."""
    return sorted({c["dialect"] for c in clips}, key=lambda d: (-judged(clips, dialect=d).rate, d))


def mean_chrf(clips: list[dict]) -> float:
    return round(mean(c["chrf"] for c in clips if "chrf" in c), 1)


def lowest_chrf(clips: list[dict]) -> str:
    """The dialect with the lowest mean chrF, ties by code: the worst by chrF alone."""
    scored = [c for c in clips if "chrf" in c]
    return min(sorted({c["dialect"] for c in scored}),
               key=lambda d: mean(c["chrf"] for c in scored if c["dialect"] == d))


def unrelated_everywhere(clips: list[dict]) -> list[int]:
    """Sentences rated in every dialect and unrelated in each."""
    dialects = {c["dialect"] for c in clips}
    labels: dict[int, dict[str, str]] = {}
    for c in clips:
        if c.get("meaning") in RATED:
            labels.setdefault(c["sentence_id"], {})[c["dialect"]] = c["meaning"]
    return sorted(s for s, seen in labels.items()
                  if seen.keys() == dialects and set(seen.values()) == {"unrelated"})


class Speech:
    """The clips of a speech run, with the cluster intervals drawn once."""

    def __init__(self, scores: dict):
        self.scores = scores
        self.clips = {"apertus": scores["apertus"], "whisper": scores["whisper"]}
        self.order = by_dialect(scores["apertus"])
        self.intervals = {name: clustered(clips) for name, clips in self.clips.items()}

    def share(self, name: str, dialect: str | None = None, verdict: str = "unrelated") -> Share:
        return judged(self.clips[name], verdict, dialect)

    @property
    def sentences(self) -> int:
        return len({c["sentence_id"] for c in self.clips["apertus"]})


def brief(at: str, stated_share: dict, s: Share) -> list[Check]:
    return [Check(f"{at}.rate", stated_share.get("rate"), round(s.rate, 3)),
            Check(f"{at}.ci95", stated_share.get("ci95"), rounded(s.wilson)),
            Check(f"{at}.k", stated_share.get("k"), s.k),
            Check(f"{at}.n", stated_share.get("n"), s.n)]


def parameter_checks(at: str, p: dict, speech: Speech) -> list[Check]:
    scores, unrelated = speech.scores, p.get("unrelated", {})
    checks = [Check(f"{at}.harness_run_id", p.get("harness_run_id"), scores["run_id"]),
              Check(f"{at}.temperature", p.get("temperature"), scores["temperature"]),
              Check(f"{at}.instruction", p.get("instruction"), scores["instruction"]),
              Check(f"{at}.whisper_model", p.get("whisper_model"), scores["whisper_model"]),
              Check(f"{at}.unrelated keys", list(unrelated), [*speech.order, "all"])]
    for d in [*speech.order, None]:
        for name in speech.clips:
            checks += brief(f"{at}.unrelated.{d or 'all'}.{name}",
                            unrelated.get(d or "all", {}).get(name, {}), speech.share(name, d))
    for name, clips in speech.clips.items():
        checks += [Check(f"{at}.unrelated_cluster_ci95.{name}",
                         p.get("unrelated_cluster_ci95", {}).get(name),
                         list(speech.intervals[name]), rounding(3)),
                   Check(f"{at}.mean_chrf.{name}", p.get("mean_chrf", {}).get(name),
                         mean_chrf(clips))]
    for verdict in RATED:
        checks += brief(f"{at}.whisper_meaning.{verdict}",
                        p.get("whisper_meaning", {}).get(verdict, {}),
                        speech.share("whisper", verdict=verdict))
    return checks


def summary_checks(at: str, summary: dict, speech: Speech) -> list[Check]:
    a, w = speech.share("apertus"), speech.share("whisper")
    worst, best = (speech.share("apertus", d) for d in (speech.order[0], speech.order[-1]))
    (a_low, a_high), (w_low, w_high) = speech.intervals["apertus"], speech.intervals["whisper"]
    over, text = f"{at} issue_summary.overview", summary["overview"]
    return [
        *stated(over, text, r"rated (\d+) of (\d+) SwissDial translations by (\S+) unrelated to "
                r"the recording \((\d+)%", {"k": a.k, "n": a.n, "model": speech.scores["model"],
                                            "unrelated %": pct(a.rate)}),
        *stated(over, text, r"\(\d+%, 95% CI (\d+)%-(\d+)% over speakers",
                {"cluster ci95 low %": a_low.percent, "cluster ci95 high %": a_high.percent},
                rounding(0)),
        *stated(over, text, rf"from (\d+)% for the {NAME} speaker to (\d+)% for the {NAME} "
                r"speaker", {"best %": pct(best.rate), "best dialect": DIALECTS[speech.order[-1]],
                             "worst %": pct(worst.rate),
                             "worst dialect": DIALECTS[speech.order[0]]}),
        *stated(over, text, rf"\(by chrF alone the {NAME} speaker is worst\)",
                {"lowest mean chrF": DIALECTS[lowest_chrf(speech.clips["apertus"])]}),
        *stated(over, text, r"from (\d+) speakers, one per dialect, each reading the same "
                r"(\d+) sentences", {"speakers": len(speech.order),
                                     "sentences": speech.sentences}),
        *stated(over, text, r"rated (\d+) of its (\d+) outputs unrelated \((\d+)%",
                {"whisper k": w.k, "whisper n": w.n, "whisper %": pct(w.rate)}),
        *stated(over, text, r"outputs unrelated \(\d+%, 95% CI (\d+)%-(\d+)%\)",
                {"whisper ci95 low %": w_low.percent, "whisper ci95 high %": w_high.percent},
                rounding(0)),
        *stated(f"{at} issue_summary.desired_behavior", summary["desired_behavior"],
                r"rated (\d+)% of \S+ outputs as keeping the meaning of the clip and (\d+)% as "
                r"keeping part", {"whisper same %": pct(speech.share("whisper", None, "same").rate),
                                  "whisper partial %":
                                      pct(speech.share("whisper", None, "partial").rate)}),
        *stated(f"{at} issue_summary.observed_behavior", summary["observed_behavior"],
                r"(\d+) of (\d+) translations", {"k": a.k, "n": a.n}, at_start=True),
        *stated(f"{at} issue_summary.self_assessed_breadth_justification",
                summary["self_assessed_breadth_justification"],
                rf"for each of the (\d+) speakers, one per dialect, at least (\d+) of (\d+) "
                rf"translations were unrelated \((\d+)% for the {NAME} speaker\)",
                {"speakers": len(speech.order), "best k": best.k, "best n": best.n,
                 "best %": pct(best.rate), "best dialect": DIALECTS[speech.order[-1]]}),
    ]


def text_checks(at: str, finding: dict, speech: Speech) -> list[Check]:
    a, w = speech.share("apertus"), speech.share("whisper")
    clips = speech.clips
    return [
        *stated(f"{at} issue_title", finding["issue_title"], r"rarely does \((\d+)%\)",
                {"whisper unrelated %": pct(w.rate)}),
        *summary_checks(at, finding["issue_summary"], speech),
        *stated(f"{at} notes", finding["notes"], r"The (\d+) clips \((\d+) speakers x (\d+) "
                r"sentences\)", {"clips": a.n, "speakers": len(speech.order),
                                 "sentences": speech.sentences}),
        *stated(f"{at} notes", finding["notes"], r"Mean chrF: Apertus (\d+\.\d), Whisper "
                r"(\d+\.\d)", {"apertus mean chrF": mean_chrf(clips["apertus"]),
                               "whisper mean chrF": mean_chrf(clips["whisper"])}),
    ]


def figure_checks(at: str, figure: dict, speech: Speech) -> list[Check]:
    rows = {row["dialect"]: row for row in figure.get("rows", [])}
    checks = [Check(f"{at}.{key}", figure.get(key), speech.scores[key])
              for key in ("model", "judge", "whisper_model")]
    checks.append(Check(f"{at}.rows dialects", list(rows), speech.order))
    for d in speech.order:
        row = rows.get(d, {})
        checks.append(Check(f"{at}.rows[{d}].name", row.get("name"), DIALECTS[d]))
        for name in speech.clips:
            checks += brief(f"{at}.rows[{d}].{name}", row.get(name, {}), speech.share(name, d))
    for name in speech.clips:
        stated_all, s = figure.get("all", {}).get(name, {}), speech.share(name)
        checks += [Check(f"{at}.all.{name}.rate", stated_all.get("rate"), round(s.rate, 3)),
                   Check(f"{at}.all.{name}.k", stated_all.get("k"), s.k),
                   Check(f"{at}.all.{name}.n", stated_all.get("n"), s.n),
                   Check(f"{at}.all.{name}.wilson_ci95", stated_all.get("wilson_ci95"),
                         rounded(s.wilson)),
                   Check(f"{at}.all.{name}.ci95", stated_all.get("ci95"),
                         list(speech.intervals[name]), rounding(3))]
    return checks + [Check(f"{at}.unrelated_in_every_dialect",
                           figure.get("unrelated_in_every_dialect"),
                           unrelated_everywhere(speech.clips["apertus"]))]
