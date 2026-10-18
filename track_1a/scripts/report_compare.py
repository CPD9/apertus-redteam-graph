"""The figures that compare two runs per language: Apertus 8B against 70B, and the 70B before and
after the mitigation system prompt, with the rates they show pooled over hypotheses."""
from __future__ import annotations

from collections import Counter
from typing import NamedTuple

from report_charts import BLUE, RED, SIZE_COLORS, bar_chart
from report_pooling import difference, pooled, resamples
from report_runs import Recorded, Skip, same_model, title

from redteam.agents import LANG_NAMES


class Arm(NamedTuple):
    run: Recorded
    name: str
    color: str
    where: str  # completes "never broken ...", e.g. "with the prompt"


def counts(rec, hypothesis, langs, seeds):
    """Wrong and total answers of one hypothesis in langs. A hypothesis the attacker never broke
    was never verified; it counts as answering every seed correctly."""
    if hypothesis not in rec.verified:
        return 0, seeds * len(langs)
    cells = [rec.verified[hypothesis]["per_lang"][lang] for lang in langs]
    return sum(c["k"] for c in cells), sum(c["n"] for c in cells)


def without_premise(rec, hypotheses):
    """The hypotheses whose last attack was not a false premise, each with that attack."""
    ended = {h: rec.last_attack[h] for h in hypotheses if h in rec.last_attack}
    return {h: strategy for h, strategy in ended.items() if strategy != "false_premise"}


def comparison(before, after, names):
    """Wrong-answer rates of two runs per language and over all languages, for every hypothesis
    both runs finished, and what the comparison rests on. None if neither verified any of them."""
    runs = (before, after)
    unbroken = [rec.ended("no_issue") for rec in runs]
    done = [h for h in before.run.hypotheses
            if all(h in rec.verified or h in never for rec, never in zip(runs, unbroken))]
    if not any(h in rec.verified for h in done for rec in runs):
        return None
    seeds = len(before.run.seeds or after.run.seeds)
    langs = [lang for lang in before.run.langs if lang in after.run.langs]
    draws = resamples(len(done))
    per_lang, change = {}, {}
    for key, group in [*((lang, [lang]) for lang in langs), ("all", langs)]:
        tables = [[counts(rec, h, group, seeds) for h in done] for rec in runs]
        per_lang[key] = {name: pooled(table, draws) for name, table in zip(names, tables)}
        change[key] = difference(*tables, draws)
    both = [h for h in done if h in before.verified and h in after.verified]
    failed = before.ended("error") | after.ended("error")
    return {"runs": {rec.id: rec.run.model for rec in runs}, "series": names,
            "judges": {name: rec.run.judge for name, rec in zip(names, runs)},
            "hypotheses": done, "answers_per_language": seeds,
            "never_broken": {name: [h for h in done if h in never]
                             for name, never in zip(names, unbroken)},
            "flagged": {name: sum(h in rec.ended("finding") for h in done)
                        for name, rec in zip(names, runs)},
            "last_attack": {name: dict(Counter(rec.last_attack[h] for h in done
                                               if h in rec.last_attack))
                            for name, rec in zip(names, runs)},
            "other_last_attack": {name: without_premise(rec, done)
                                  for name, rec in zip(names, runs)},
            "uncounted": {name: sorted(rec.uncounted) for name, rec in zip(names, runs)},
            "failed": [h for h in before.run.hypotheses
                       if h in after.run.hypotheses and h not in done and h in failed],
            "verified_in_both": len(both),
            "same_prompts": sum(before.run.prompts[h] == after.run.prompts[h] for h in both),
            "per_lang": per_lang, "difference": change}


def judge_sentence(runs):
    judges = sorted({rec.run.judge for rec in runs} - {None})
    if len(judges) != 1:
        return f" Judges: {', '.join(judges)}." if judges else ""
    own = [rec.name for rec in runs if same_model(judges[0], rec.run.model)]
    return f" Judge: {judges[0]}" + (f", so {own[0]} judged its own answers." if own else ".")


def compare_note(arms, numbers):
    unbroken = [f"{len(numbers['never_broken'][arm.name])} {arm.where}" for arm in arms
                if numbers["never_broken"][arm.name]]
    note = (f"Wrong answers over the {len(numbers['hypotheses'])} hypotheses attacked in "
            "both runs; 95% CI from resampling hypotheses.")
    if unbroken:
        note += (f" Never broken, so 0 of {numbers['answers_per_language']} answers per "
                 f"language: {' and '.join(unbroken)}.")
    note += (f" Each run attacked adaptively, and {numbers['same_prompts']} of the "
             f"{numbers['verified_in_both']} hypotheses verified in both used the same prompts.")
    if numbers["failed"]:
        note += f" Left out after an error: {', '.join(map(title, numbers['failed']))}."
    return note + judge_sentence([arm.run for arm in arms])


def compare(before, after, heading):
    numbers = comparison(before.run, after.run, [before.name, after.name])
    if numbers is None:
        raise Skip(f"runs {before.run.id} and {after.run.id} have no verified hypothesis that "
                   "both finished")
    rows = [(LANG_NAMES.get(key, "All languages"), list(entries.values()), None)
            for key, entries in numbers["per_lang"].items()]
    svg = bar_chart(rows, [(before.name, before.color), (after.name, after.color)],
                    compare_note((before, after), numbers), heading, total=True)
    return svg, numbers


def languages_by_size(small, large):
    return compare(Arm(small, small.name, SIZE_COLORS[0], f"on {small.name}"),
                   Arm(large, large.name, SIZE_COLORS[1], f"on {large.name}"),
                   f"Share of wrong answers per language, {small.name} versus {large.name}")


def mitigation(mitigated, baselines):
    before = next((rec for rec in baselines
                   if rec and rec.run.model == mitigated.run.model and not rec.run.system), None)
    if before is None:
        raise Skip(f"no run of {mitigated.run.model} without a system prompt to compare against")
    svg, numbers = compare(Arm(before, "No system prompt", RED, "without the prompt"),
                           Arm(mitigated, "Mitigation system prompt", BLUE, "with the prompt"),
                           "Share of wrong answers per language before and after the mitigation "
                           f"system prompt, {before.name}")
    return svg, numbers | {"system_prompt": mitigated.run.system}
