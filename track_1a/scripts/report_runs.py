"""Recorded runs as the report figures need them, and wrong-answer rates pooled across hypotheses.

A run is read with redteam.answers and counted the way the findings count (Answer.confirmed): an
answer counts when it states the error. A hypothesis whose calls are not in the LLM cache keeps the
judge's logged flags, and a note on stderr says so.

The answers to one hypothesis share a prompt, so they are not independent of each other. Pooled
rates therefore get their interval from resampling whole hypotheses rather than from the count
of answers, which would make the interval far too narrow.
"""
from __future__ import annotations

import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from redteam import answers, paths
from redteam.cache import CACHE_DIR
from redteam.events import read_events
from redteam.run import load_hypotheses

CACHE = CACHE_DIR
DRAWS = 4000
HYPOTHESES = {h["id"]: h for h in load_hypotheses()}


class Skip(Exception):
    """A figure whose inputs are missing; report_figures.main reports it in one line."""


def note(message):
    print(f"note: {message}", file=sys.stderr)


def title(hypothesis):
    """The short title the hypothesis banks give an id; an id they do not know stays as it is."""
    return HYPOTHESES.get(hypothesis, {}).get("title", hypothesis)


@dataclass
class Recorded:
    """A recorded run: what its event log says, and the verifier result of each verified
    hypothesis (per_lang cells with k, n, rate and ci95; overall), counting confirmed answers."""
    run: answers.Run
    dir: Path
    verified: dict
    uncounted: set  # not replayable, so their cells count the judge's logged flags
    last_attack: dict  # hypothesis -> strategy of the attacker's last attempt

    @property
    def id(self):
        return self.run.id

    @property
    def name(self):
        return self.run.model.rsplit("/", 1)[-1]

    def ended(self, outcome):
        """Hypotheses whose attack ended so: "finding" (flagged at the bar), "no_issue" or
        "error"."""
        return {h for h, o in self.run.outcome.items() if o == outcome}


def locate(ref):
    """A run folder, given as a path or as an id looked up like redteam.paths does."""
    found = Path(ref) if Path(ref).is_dir() else paths.run_dir(str(ref))
    if found is None:
        raise SystemExit(f"run {ref} not found in {paths.RUNS} or {paths.SHIPPED}")
    return found


def recorded(ref):
    """A recorded run, its verifier results counted like the findings where the cache allows."""
    run_dir = locate(ref)
    run, _ = answers.read_run(run_dir)
    events = read_events(run_dir / "events.jsonl")
    verified = {e["hypothesis"]: e["data"] for e in events
                if (e["node"], e["status"]) == ("verifier", "done")}
    # Later attempts overwrite earlier ones, so each hypothesis keeps the attack it ended with.
    last_attack = {e["hypothesis"]: e["data"]["strategy"] for e in events
                   if (e["node"], e["status"]) == ("attacker", "done")}
    uncounted = answers.recount(run_dir, verified, HYPOTHESES, CACHE)
    if uncounted:
        note(f"run {run.id}: {len(uncounted)} of {len(verified)} verified hypotheses cannot be "
             "replayed from the cache; they count the judge's logged flags")
    if not (run_dir / "summary.json").exists():
        note(f"run {run.id} is still in progress; using its {len(verified)} verified hypotheses "
             "so far")
    return Recorded(run, run_dir, verified, uncounted, last_attack)


def control_shares(rec, controls):
    """Premise and neutral shares per hypothesis, both counted with Answer.confirmed. A control
    row that cannot be replayed falls back to its logged rates in control.json."""
    shares = answers.control_shares(rec.dir, controls, HYPOTHESES, CACHE)
    missing = [c for c in controls if c["id"] not in shares]
    if missing:
        note(f"the control of run {rec.id}: {len(missing)} of {len(controls)} rows cannot be "
             "replayed; using its logged rates for them")
    for c in missing:
        shares[c["id"]] = (logged(c["premise_rate"], rec.verified[c["id"]]),
                           logged(c["neutral_rate"], c["neutral_answers"]))
    return shares


def logged(rate, cells):
    n = (sum(c["n"] for c in cells["per_lang"].values()) if "per_lang" in cells
         else sum(len(texts) for texts in cells.values()))
    return answers.Share(round(rate * n), n)


def same_model(alias, model):
    """Whether a served alias such as apertus-70b-fp8 names the model with the full id
    onprem-ai/Apertus-v1.5-70B-FP8. Aliases drop parts of the id but keep the rest."""
    def parts(name):
        return set(re.split(r"[-_./]", name.lower()))
    return parts(alias) <= parts(model)


def counts(rec, hypothesis, langs, seeds):
    """Wrong and total answers of one hypothesis in langs. A hypothesis the attacker never broke
    was never verified; it counts as answering every seed correctly."""
    if hypothesis not in rec.verified:
        return 0, seeds * len(langs)
    cells = [rec.verified[hypothesis]["per_lang"][lang] for lang in langs]
    return sum(c["k"] for c in cells), sum(c["n"] for c in cells)


def resamples(size):
    rng = random.Random(1)  # fixed, so rebuilding the figures does not move the intervals
    return [Counter(rng.choices(range(size), k=size)) for _ in range(DRAWS)]


def rate(table, weights):
    return (sum(w * table[i][0] for i, w in weights.items())
            / sum(w * table[i][1] for i, w in weights.items()))


def interval(values):
    values = sorted(values)
    return [round(values[round(q * (len(values) - 1))], 4) for q in (0.025, 0.975)]


def totals(table):
    return sum(c[0] for c in table), sum(c[1] for c in table)


def pooled(table, draws):
    k, n = totals(table)
    return {"k": k, "n": n, "rate": round(k / n, 4),
            "ci95": interval(rate(table, d) for d in draws)}


def difference(before, after, draws):
    """Change in the pooled rate from before to after, both resampled with the same hypotheses."""
    (k0, n0), (k1, n1) = totals(before), totals(after)
    return {"rate": round(k1 / n1 - k0 / n0, 4),
            "ci95": interval(rate(after, d) - rate(before, d) for d in draws)}


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
