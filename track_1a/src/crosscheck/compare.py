"""Two runs compared per language over the hypotheses both finished: Apertus 8B against 70B, and
the 70B before and after the mitigation system prompt. A pooled rate's interval resamples
hypotheses, as the answers to one hypothesis share its prompt."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import cached_property

from .bounds import Bound
from .checks import Check, rounding
from .rates import hypothesis_draws, quantile, resampled
from .runs import Run


@dataclass
class Comparison:
    names: list[str]
    runs: tuple[Run, Run]
    done: list[str]  # verified, or never broken, in both runs
    tables: dict[str, list[list[tuple[int, int]]]]  # language or "all" -> per run, per hypothesis

    def pooled(self, key: str, arm: int) -> dict:
        table = self.tables[key][arm]
        k, n = (sum(cell[i] for cell in table) for i in (0, 1))
        return {"k": k, "n": n, "rate": k / n}

    def change(self, key: str) -> float:
        return self.pooled(key, 1)["rate"] - self.pooled(key, 0)["rate"]

    @cached_property
    def intervals(self) -> dict[str, dict[str, list[Bound]]]:
        return self.drawn(hypothesis_draws(len(self.done)))

    def drawn(self, draws: list[dict[int, int]]) -> dict[str, dict[str, list[Bound]]]:
        """Per language or "all": the 95% interval of each run's pooled rate and of the change,
        every rate of one draw over the same resampled hypotheses."""
        out = {}
        for key, (before, after) in self.tables.items():
            rates = [(resampled(before, w), resampled(after, w)) for w in draws]
            out[key] = {name: [Bound.drawn(quantile(values, q)) for q in (0.025, 0.975)]
                        for name, values in (("before", [b for b, _ in rates]),
                                             ("after", [a for _, a in rates]),
                                             ("change", [a - b for b, a in rates]))}
        return out


def counted(run: Run, hypothesis: str, langs: list[str], seeds: int) -> tuple[int, int]:
    """Counted and all answers of a hypothesis in some languages. One the attacker never broke
    was never verified and counts as right in every seed."""
    if hypothesis not in run.logged_n:
        return 0, seeds * len(langs)
    verdicts = [v for v in run.of({hypothesis}) if v.lang in langs]
    return sum(v.counted for v in verdicts), len(verdicts)


def compare(before: Run, after: Run, names: list[str]) -> Comparison:
    runs = (before, after)
    done = [h for h in before.hypotheses
            if all(h in run.logged_n or run.outcome.get(h) == "no_issue" for run in runs)]
    seeds = len(before.seeds or after.seeds)
    langs = [lang for lang in before.langs if lang in after.langs]
    groups = {**{lang: [lang] for lang in langs}, "all": langs}
    tables = {key: [[counted(run, h, group, seeds) for h in done] for run in runs]
              for key, group in groups.items()}
    return Comparison(names, runs, done, tables)


def miscounted(run: Run, done: list[str]) -> list[str]:
    """Verified hypotheses whose replayed answers per language differ from what the verifier
    logged, so their counts would rest on something other than the replay."""
    return sorted(h for h in done if h in run.logged_n and any(
        sum(v.lang == lang for v in run.of({h})) != n for lang, n in run.logged_n[h].items()))


def per_name(c: Comparison, value) -> dict:
    return {name: value(run) for name, run in zip(c.names, c.runs)}


def facts(c: Comparison) -> dict:
    before, after = c.runs
    both = [h for h in c.done if h in before.logged_n and h in after.logged_n]
    failed = set(before.ended("error")) | set(after.ended("error"))
    return {
        "runs": {run.id: run.model for run in c.runs},
        "judges": per_name(c, lambda run: run.judge),
        "hypotheses": c.done,
        "answers_per_language": len(before.seeds or after.seeds),
        "never_broken": per_name(c, lambda run: [h for h in c.done
                                                 if run.outcome.get(h) == "no_issue"]),
        "flagged": per_name(c, lambda run: sum(run.outcome.get(h) == "finding" for h in c.done)),
        "last_attack": per_name(c, lambda run: dict(Counter(
            run.last_attack[h] for h in c.done if h in run.last_attack))),
        "other_last_attack": per_name(c, lambda run: {
            h: run.last_attack[h] for h in c.done
            if h in run.last_attack and run.last_attack[h] != "false_premise"}),
        "uncounted": per_name(c, lambda run: miscounted(run, c.done)),
        "failed": [h for h in before.hypotheses
                   if h in after.hypotheses and h not in c.done and h in failed],
        "verified_in_both": len(both),
        "same_prompts": sum(before.prompts[h] == after.prompts[h] for h in both),
    }


def comparison_checks(at: str, stated: dict, c: Comparison) -> list[Check]:
    checks = [Check(f"{at}.series", stated.get("series"), c.names)]
    checks += [Check(f"{at}.{key}", stated.get(key), mine) for key, mine in facts(c).items()]
    drawn = c.intervals
    for key in c.tables:
        for arm, name in enumerate(c.names):
            mine, said = c.pooled(key, arm), stated.get("per_lang", {}).get(key, {}).get(name, {})
            where = f"{at}.per_lang.{key}.{name}"
            checks += [Check(f"{where}.k", said.get("k"), mine["k"]),
                       Check(f"{where}.n", said.get("n"), mine["n"]),
                       Check(f"{where}.rate", said.get("rate"), round(mine["rate"], 4)),
                       Check(f"{where}.ci95", said.get("ci95"),
                             drawn[key]["before" if arm == 0 else "after"], rounding(4))]
        said = stated.get("difference", {}).get(key, {})
        checks += [Check(f"{at}.difference.{key}.rate", said.get("rate"), round(c.change(key), 4)),
                   Check(f"{at}.difference.{key}.ci95", said.get("ci95"),
                         drawn[key]["change"], rounding(4))]
    return checks
