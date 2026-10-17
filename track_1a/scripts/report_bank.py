"""Every hypothesis of a run counted on its own, for a run that no finding groups (bank 2 on the
70B): how many of its answers count, as the findings count them, and how its attack ended.

A hypothesis that stopped with an error keeps the answers verified before it stopped, but is not
reproduced: the report's bar asks for all of its answers.
"""
from __future__ import annotations

import report_runs
from report_runs import HYPOTHESES, locate, note, title

from redteam import answers, shares
from redteam.graph import Config

VERIFIED = {"finding", "not_reproducible"}  # the verifier finished, whatever the judge's flags


def row(run, hypothesis):
    counted = shares.share(shares.of(run.answers, {hypothesis}))
    status = run.outcome.get(hypothesis, "unfinished")
    return {"id": hypothesis, "title": title(hypothesis), "status": status,
            "k": counted.k, "n": counted.n, "rate": round(counted.rate, 4),
            "reproduced": status in VERIFIED and counted.rate >= Config.min_rate}


def hypothesis_counts(ref):
    run = answers.load_run(locate(ref), HYPOTHESES, report_runs.CACHE, partial=True)
    if run.unreplayed:
        note(f"run {run.id}: {len(run.unreplayed)} hypotheses cannot be replayed from the cache, "
             "so none of their answers are counted")
    return {"run": run.id, "model": run.model, "bar": Config.min_rate,
            "unreplayed": run.unreplayed, "rows": [row(run, h) for h in run.hypotheses]}
