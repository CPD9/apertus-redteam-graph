"""Recorded runs as the report figures need them, and violation rates pooled across hypotheses.

The answers to one hypothesis share a prompt, so they are not independent of each other. Pooled
rates therefore get their interval from resampling whole hypotheses rather than from the count
of answers, which would make the interval far too narrow.
"""
from __future__ import annotations

import json
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from redteam import answers  # noqa: E402
from redteam.cache import CACHE_DIR  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

RUNS = ROOT / "runs"
DRAWS = 4000


@dataclass
class Run:
    id: str
    dir: Path
    model: str
    judge: str | None
    langs: list
    system: str | None
    attacked: list         # hypothesis ids in the order the run was given them
    verified: dict         # hypothesis -> data of its verifier "done" event
    prompts: dict          # hypothesis -> prompts per language of its last attempt
    findings: set
    unbroken: set          # hypotheses the attacker did not break in any attempt
    failed: set            # hypotheses that ended in an error
    seeds: int | None      # answers per language in a verification

    @property
    def name(self):
        return self.model.rsplit("/", 1)[-1]


def read_events(path):
    events = []
    for line in path.read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a run that is still writing can end in a half-written line
    return events


def load_run(ref):
    run_dir = Path(ref) if Path(ref).is_dir() else RUNS / ref
    events = read_events(run_dir / "events.jsonl")

    def data(node, status):
        return {e["hypothesis"]: e["data"] for e in events
                if e["node"] == node and e["status"] == status}

    start = data("graph", "start")[None]
    run = Run(id=events[0]["run_id"], dir=run_dir, model=events[0]["model"],
              judge=start.get("red_model"), langs=start["langs"], system=start.get("system"),
              attacked=start["hypotheses"], verified=data("verifier", "done"),
              prompts={h: d["prompts"] for h, d in data("mutator", "done").items()},
              findings=set(data("scribe", "done")), unbroken=set(data("graph", "no_issue")),
              failed=set(data("graph", "error")),
              seeds=max((len(d["seeds"]) for d in data("verifier", "start").values()),
                        default=None))
    recount(run, run_dir)
    if not (run_dir / "summary.json").exists():
        print(f"note: run {run.id} is still in progress; using its {len(run.verified)} "
              "verified hypotheses so far")
    return run


def recount(run, run_dir):
    """Count only answers that assert the error (answers.Answer.confirmed), as the findings do."""
    refs = {h["id"]: h for h in load_hypotheses()}
    if not answers.recount(run_dir, run.verified, refs) and run.verified:
        print(f"note: run {run.id} cannot be replayed; using its logged verdict flags")


def control_shares(run, controls):
    """Premise and neutral shares per hypothesis, both counted with Answer.confirmed. Runs that
    cannot be replayed fall back to the logged rates of control.json."""
    refs = {h["id"]: h for h in load_hypotheses()}
    shares = answers.control_shares(run.dir, controls, refs, CACHE_DIR)
    if not shares:
        print(f"note: control of run {run.id} cannot be replayed; using its logged rates")
        return {c["id"]: (logged(c["premise_rate"], run.verified[c["id"]]),
                          logged(c["neutral_rate"], c["neutral_answers"])) for c in controls}
    return shares


def logged(rate, cells):
    n = (sum(c["n"] for c in cells["per_lang"].values()) if "per_lang" in cells
         else sum(len(texts) for texts in cells.values()))
    return answers.Share(round(rate * n), n)


ACRONYMS = {"ahv", "ahv21", "kvg", "eu", "ip", "rav", "bac", "fadp"}


def readable(hypothesis):
    """vote_double_majority_half_cantons -> Double majority half cantons (domain prefix dropped)."""
    words = hypothesis.split("_")[1:] or [hypothesis]
    words = [w.upper() if w in ACRONYMS else w for w in words]
    return " ".join(words)[:1].upper() + " ".join(words)[1:]


def same_model(alias, model):
    """Whether a served alias such as apertus-70b-fp8 names the model with the full id
    onprem-ai/Apertus-v1.5-70B-FP8. Aliases drop parts of the id but keep the rest."""
    def parts(name):
        return set(re.split(r"[-_./]", name.lower()))
    return parts(alias) <= parts(model)


def counts(run, hypothesis, langs, seeds):
    """Violating and total answers of one hypothesis in langs. A hypothesis the attacker never
    broke was never verified; it counts as answering every seed correctly."""
    if hypothesis not in run.verified:
        return 0, seeds * len(langs)
    cells = [run.verified[hypothesis]["per_lang"][lang] for lang in langs]
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


def comparison(before, after, names):
    """Violation rates of two runs per language and over all languages, for every hypothesis
    both runs finished, and what the comparison rests on. None if neither verified any of them."""
    runs = (before, after)
    done = [h for h in before.attacked if all(h in r.verified or h in r.unbroken for r in runs)]
    if not any(h in run.verified for h in done for run in runs):
        return None
    seeds = before.seeds or after.seeds
    langs = [lang for lang in before.langs if lang in after.langs]
    draws = resamples(len(done))
    per_lang, change = {}, {}
    for key, group in [*((lang, [lang]) for lang in langs), ("all", langs)]:
        tables = [[counts(run, h, group, seeds) for h in done] for run in runs]
        per_lang[key] = {name: pooled(table, draws) for name, table in zip(names, tables)}
        change[key] = difference(*tables, draws)
    both = [h for h in done if h in before.verified and h in after.verified]
    left_out = [h for h in before.attacked if h in after.attacked and h not in done]
    return {"runs": {run.id: run.model for run in runs}, "series": names,
            "judges": {name: run.judge for name, run in zip(names, runs)},
            "hypotheses": done, "answers_per_language": seeds,
            "never_broken": {name: [h for h in done if h in run.unbroken]
                             for name, run in zip(names, runs)},
            "findings": {name: sum(h in run.findings for h in done)
                         for name, run in zip(names, runs)},
            "failed": [h for h in left_out if h in before.failed or h in after.failed],
            "verified_in_both": len(both),
            "same_prompts": sum(before.prompts[h] == after.prompts[h] for h in both),
            "per_lang": per_lang, "difference": change}
