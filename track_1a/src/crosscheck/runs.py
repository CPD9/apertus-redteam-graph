"""A recorded run read from its event log, with the verdict of every verified answer replayed
from the cache: the log keeps the judge's flag but not the severity that decides what counts.
The logged flag is kept, so the replayed one can be held against it."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from redteam.events import read_events

from .replies import Missing, Replies
from .verdicts import counts, flag_and_severity

# A hypothesis is left out whole when one of its calls is missing, its hypothesis is no longer
# in the banks, or a judge reply does not parse.
UNREPLAYABLE = (Missing, KeyError, ValueError)


@dataclass(frozen=True)
class Verdict:
    hypothesis: str
    lang: str
    seed: int
    flagged: bool
    severity: int

    @property
    def counted(self) -> bool:
        return counts(self.flagged, self.severity)


@dataclass
class Run:
    id: str
    model: str
    judge: str
    system: str | None
    langs: list[str]
    seeds: list[int] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)  # in the order the run was given them
    outcome: dict[str, str] = field(default_factory=dict)  # finding, not_reproducible, ...
    prompts: dict[str, dict[str, str]] = field(default_factory=dict)  # last attempt, by language
    last_attack: dict[str, str] = field(default_factory=dict)
    logged_n: dict[str, dict[str, int]] = field(default_factory=dict)  # verifier done, per language
    logged_flags: dict[tuple[str, str, int], bool] = field(default_factory=dict)
    verdicts: list[Verdict] = field(default_factory=list)
    unreplayed: list[str] = field(default_factory=list)

    def of(self, ids) -> list[Verdict]:
        return [v for v in self.verdicts if v.hypothesis in ids]

    def ended(self, outcome: str) -> list[str]:
        return [h for h in self.hypotheses if self.outcome.get(h) == outcome]


def read(run_dir: Path, refs: dict[str, dict], replies: Replies) -> Run:
    events = read_events(run_dir / "events.jsonl")
    first, start = events[0], events[0]["data"]
    run = Run(run_dir.name, first["model"], start.get("red_model") or first["model"],
              start.get("system"), start["langs"])
    outcome, cells = {}, []
    for event in events:
        hyp, data, step = event["hypothesis"], event["data"], (event["node"], event["status"])
        if step == ("attacker", "done"):
            run.last_attack[hyp] = data["strategy"]
        elif step == ("mutator", "done"):
            run.prompts[hyp] = data["prompts"]
        elif step == ("verifier", "start"):
            run.seeds = data["seeds"]
        elif step == ("verifier", "progress"):
            cells.append((hyp, data["lang"], data["seed"], run.prompts[hyp][data["lang"]]))
            run.logged_flags[hyp, data["lang"], data["seed"]] = data["violation"]
        elif step == ("verifier", "done"):
            run.logged_n[hyp] = {lang: cell["n"] for lang, cell in data["per_lang"].items()}
        elif step == ("scribe", "done"):
            outcome[hyp] = "finding"
        elif event["node"] == "graph" and hyp:
            outcome[hyp] = event["status"]
    named = start.get("hypotheses", [])
    run.hypotheses = list(dict.fromkeys([*named, *outcome, *(cell[0] for cell in cells)]))
    run.outcome = {h: outcome[h] for h in run.hypotheses if h in outcome}
    replay(run, cells, refs, replies)
    return run


def unlike_log(run: Run) -> int:
    """Replayed verdicts whose flag is not the one the verifier logged for that answer."""
    return sum(v.flagged != run.logged_flags.get((v.hypothesis, v.lang, v.seed))
               for v in run.verdicts)


def replay(run: Run, cells: list[tuple], refs: dict[str, dict], replies: Replies) -> None:
    for hypothesis in dict.fromkeys(cell[0] for cell in cells):
        try:
            run.verdicts += [verified(run, replies, refs[hyp]["reference"], hyp, lang, seed, prompt)
                             for hyp, lang, seed, prompt in cells if hyp == hypothesis]
        except UNREPLAYABLE:
            run.unreplayed.append(hypothesis)


def verified(run: Run, replies: Replies, reference: str, hyp: str, lang: str, seed: int,
             prompt: str) -> Verdict:
    answer = replies.answer(run.model, prompt, seed, run.system)
    return judged(run, replies, reference, hyp, lang, seed, prompt, answer)


def judged(run: Run, replies: Replies, reference: str, hyp: str, lang: str, seed: int,
           prompt: str, answer: str) -> Verdict:
    flagged, severity = flag_and_severity(replies.claims(run.judge, reference, prompt, answer))
    return Verdict(hyp, lang, seed, flagged, severity)


def neutral(rows: list[dict], run: Run, refs: dict[str, dict],
            replies: Replies) -> tuple[list[Verdict], list[str]]:
    """The verdicts on a control.json's neutral answers, sampled with the run's seeds in order and
    judged by the run's judge; and the rows that cannot be replayed."""
    verdicts, unreplayed = [], []
    for row in rows:
        try:
            reference = refs[row["id"]]["reference"]
            verdicts += [judged(run, replies, reference, row["id"], lang, seed,
                                row["neutral_prompts"][lang], text)
                         for lang, texts in row["neutral_answers"].items()
                         for seed, text in zip(run.seeds, texts, strict=True)]
        except UNREPLAYABLE:
            unreplayed.append(row["id"])
    return verdicts, unreplayed
