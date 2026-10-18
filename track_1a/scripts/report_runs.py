"""Recorded runs as the report figures need them.

A run is read with redteam.answers and counted the way the findings count (Answer.confirmed): an
answer counts when it states the error. When a hypothesis's calls are not in the LLM cache,
recorded() falls back to the judge's logged flags and hypothesis_counts() leaves its answers
uncounted; either way a note on stderr says so.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from redteam import answers, paths, shares
from redteam.cache import CACHE_DIR
from redteam.events import read_events
from redteam.graph import Config
from redteam.run import load_hypotheses

CACHE = CACHE_DIR
HYPOTHESES = {h["id"]: h for h in load_hypotheses()}
VERIFIER_FINISHED = {"finding", "not_reproducible"}  # whatever the judge's flags said


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
    counted = answers.control_shares(rec.dir, controls, HYPOTHESES, CACHE)
    missing = [c for c in controls if c["id"] not in counted]
    if missing:
        note(f"the control of run {rec.id}: {len(missing)} of {len(controls)} rows cannot be "
             "replayed; using its logged rates for them")
    for c in missing:
        counted[c["id"]] = (logged(c["premise_rate"], rec.verified[c["id"]]),
                            logged(c["neutral_rate"], c["neutral_answers"]))
    return counted


def logged(rate, cells):
    n = (sum(c["n"] for c in cells["per_lang"].values()) if "per_lang" in cells
         else sum(len(texts) for texts in cells.values()))
    return shares.Share(round(rate * n), n)


def same_model(alias, model):
    """Whether a served alias such as apertus-70b-fp8 names the model with the full id
    onprem-ai/Apertus-v1.5-70B-FP8. Aliases drop parts of the id but keep the rest."""
    def parts(name):
        return set(re.split(r"[-_./]", name.lower()))
    return parts(alias) <= parts(model)


def hypothesis_counts(ref):
    """Every hypothesis of a run counted on its own, for a run that no finding groups (bank 2 on
    the 70B): how many of its answers count, as the findings count them, and how its attack
    ended. A hypothesis that stopped with an error keeps the answers verified before it stopped,
    but is not reproduced: the report's bar asks for all of its answers."""
    run = answers.load_run(locate(ref), HYPOTHESES, CACHE, partial=True)
    if run.unreplayed:
        note(f"run {run.id}: {len(run.unreplayed)} hypotheses cannot be replayed from the cache, "
             "so none of their answers are counted")
    return {"run": run.id, "model": run.model, "bar": Config.min_rate, "unreplayed": run.unreplayed,
            "rows": [hypothesis_row(run, h) for h in run.hypotheses]}


def hypothesis_row(run, hypothesis):
    share = shares.share(shares.of(run.answers, {hypothesis}))
    status = run.outcome.get(hypothesis, "unfinished")
    return {"id": hypothesis, "title": title(hypothesis), "status": status,
            "k": share.k, "n": share.n, "rate": round(share.rate, 4),
            "reproduced": status in VERIFIER_FINISHED and share.rate >= Config.min_rate}
