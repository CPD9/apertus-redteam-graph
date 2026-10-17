"""The figures that compare two runs per language: Apertus 8B against 70B, and the 70B before and
after the mitigation system prompt (report_runs.comparison counts them)."""
from __future__ import annotations

from typing import NamedTuple

from report_charts import BLUE, RED, SIZE_COLORS, bar_chart
from report_runs import Recorded, Skip, comparison, same_model, title

from redteam.agents import LANG_NAMES


class Arm(NamedTuple):
    run: Recorded
    name: str
    color: str
    where: str  # completes "never broken ...", e.g. "with the prompt"


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
