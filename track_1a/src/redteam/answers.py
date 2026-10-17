"""Every verified answer of a run with its full verdict, and the counting rule shared by findings,
figures and the dashboard: an answer counts when it asserts the error (Answer.confirmed).

The event log keeps only each verdict's flag and the first 3000 characters of the answer, so the
answer and the judge's severity and quote are replayed from the LLM cache, which holds every call.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import agents
from .cache import CACHE_DIR, Cached, CacheMiss
from .events import read_events
from .graph import Config
from .judge import judge
from .llm import Router
from .shares import Share, of, share

# Why a hypothesis cannot be replayed: a call is not cached, the hypothesis is no longer in the
# banks, or a cached judge reply does not parse.
UNREPLAYABLE = (CacheMiss, KeyError, ValueError)


@dataclass(frozen=True)
class Answer:
    hypothesis: str
    lang: str
    seed: int
    prompt: str
    text: str
    flagged: bool  # the harness's verdict: a contradicted claim or undesired behaviour
    severity: int
    evidence: str

    @property
    def confirmed(self) -> bool:
        return agents.counts(self.flagged, self.severity)


@dataclass(frozen=True)
class Cell:
    """One verified answer as the event log names it."""
    hypothesis: str
    lang: str
    seed: int
    prompt: str


@dataclass
class Run:
    id: str
    model: str
    judge: str
    backend: str
    system: str | None
    langs: list[str]
    hypotheses: list[str] = field(default_factory=list)  # in the order the run was given them
    seeds: list[int] = field(default_factory=list)
    prompts: dict[str, dict[str, str]] = field(default_factory=dict)  # last attempt, by language
    outcome: dict[str, str] = field(default_factory=dict)  # finding, not_reproducible, error, ...
    answers: list[Answer] = field(default_factory=list)  # by hypothesis, language, then seed
    unreplayed: list[str] = field(default_factory=list)  # left out by load_run(partial=True)


def read_run(run_dir: Path) -> tuple[Run, list[Cell]]:
    """A run and its verified answers as the event log records them, in the order of the run's
    hypotheses and languages whatever order the threads logged them in. Nothing is replayed."""
    events = read_events(run_dir / "events.jsonl")
    start = events[0]
    run = Run(id=run_dir.name, model=start["model"], backend=start["backend"],
              judge=start["data"].get("red_model") or start["model"],
              system=start["data"].get("system"), langs=start["data"]["langs"])
    outcome, cells = {}, []
    for event in events:
        hyp, data, step = event["hypothesis"], event["data"], (event["node"], event["status"])
        if step == ("mutator", "done"):
            run.prompts[hyp] = data["prompts"]
        elif step == ("verifier", "start"):
            run.seeds = data["seeds"]
        elif step == ("verifier", "progress"):
            cells.append(Cell(hyp, data["lang"], data["seed"], run.prompts[hyp][data["lang"]]))
        elif step == ("scribe", "done"):
            outcome[hyp] = "finding"
        elif event["node"] == "graph" and hyp:
            outcome[hyp] = event["status"]
    named = start["data"].get("hypotheses", [])  # early runs did not log them
    run.hypotheses = list(dict.fromkeys([*named, *outcome, *(c.hypothesis for c in cells)]))
    run.outcome = {h: outcome[h] for h in run.hypotheses if h in outcome}
    order = {h: i for i, h in enumerate(run.hypotheses)}
    langs = {lang: i for i, lang in enumerate(run.langs)}
    cells.sort(key=lambda c: (order[c.hypothesis], langs.get(c.lang, len(langs)), c.seed))
    return run, cells


def load_run(run_dir: Path, refs: dict[str, dict], cache_root: Path,
             partial: bool = False) -> Run:
    """A run as its event log records it, so unfinished runs load too, with every verified answer
    and its verdict replayed from the LLM cache. A hypothesis that cannot be replayed raises, or
    with partial=True is left out of the answers and listed in Run.unreplayed."""
    run, cells = read_run(run_dir)
    llm = replayer(run, cache_root)
    for hypothesis in run.hypotheses:
        try:
            run.answers += [replay(llm, run, refs[c.hypothesis], c) for c in cells
                            if c.hypothesis == hypothesis]
        except UNREPLAYABLE:
            if not partial:
                raise
            run.unreplayed.append(hypothesis)
    return run


def recount(run_dir: Path, verified: dict[str, dict], refs: dict[str, dict],
            cache_root: Path = CACHE_DIR) -> set[str]:
    """Rewrite verifier results (per-language k, rate and CI, overall rate and CI) so they count
    only confirmed answers. Each hypothesis is replayed on its own; the ones that cannot be
    replayed in full keep their logged flags and are returned."""
    if not verified:
        return set()
    try:
        run = load_run(run_dir, refs, cache_root, partial=True)
    except (OSError, ValueError, KeyError, IndexError):  # no log, or one without a start event
        return set(verified)
    uncounted = set()
    for hypothesis, data in verified.items():
        replayed = of(run.answers, {hypothesis})
        cells = data.get("per_lang")  # early runs logged only rates
        if not cells or len(replayed) != sum(c["n"] for c in cells.values()):
            uncounted.add(hypothesis)
            continue
        for lang, cell in cells.items():
            counted = Share(sum(a.confirmed for a in replayed if a.lang == lang), cell["n"])
            cell.update(k=counted.k, rate=counted.rate, ci95=list(counted.ci95))
        total = Share(sum(c["k"] for c in cells.values()), sum(c["n"] for c in cells.values()))
        data["overall"], data["overall_ci95"] = total.rate, list(total.ci95)
    return uncounted


def replayer(run: Run, cache_root: Path) -> Router:
    return Router(Cached(None, run.model, replay=True, root=cache_root),
                  Cached(None, run.judge, replay=True, root=cache_root))


def replay(llm, run: Run, hyp: dict, cell: Cell) -> Answer:
    text = agents.target(llm, cell.prompt, cell.seed, Config.temperature, run.system)
    return judged(llm, hyp, cell.lang, cell.seed, cell.prompt, text)


def judged(llm, hyp: dict, lang: str, seed: int, prompt: str, text: str) -> Answer:
    verdict = judge(llm, hyp, prompt, text)
    return Answer(hyp["id"], lang, seed, prompt, text, verdict["violation"], verdict["severity"],
                  verdict["evidence"])


def neutral_answers(rows: list[dict], refs: dict[str, dict], run: Run, cache_root: Path,
                    partial: bool = False) -> list[Answer]:
    """The answers of a control.json (redteam.control), with verdicts read back like a run's. The
    control samples each language with the run's seeds, in their order. A row that cannot be
    replayed raises, or with partial=True is left out."""
    llm = replayer(run, cache_root)
    out = []
    for row in rows:
        try:
            out += [judged(llm, refs[row["id"]], lang, seed, row["neutral_prompts"][lang], text)
                    for lang, texts in row["neutral_answers"].items()
                    for seed, text in zip(run.seeds, texts, strict=True)]
        except UNREPLAYABLE:
            if not partial:
                raise
    return out


def control_shares(run_dir: Path, rows: list[dict], refs: dict[str, dict],
                   cache_root: Path = CACHE_DIR) -> dict[str, tuple[Share, Share]]:
    """Premise and neutral share per row of a control.json, both counted like the findings. A row
    whose hypothesis or neutral answers cannot be replayed is left out."""
    try:
        run = load_run(run_dir, refs, cache_root, partial=True)
    except (OSError, ValueError, KeyError, IndexError):  # no log, or one without a start event
        return {}
    neutral = neutral_answers(rows, refs, run, cache_root, partial=True)
    replayed = {a.hypothesis for a in neutral} - set(run.unreplayed)
    return {row["id"]: (share(of(run.answers, {row["id"]})), share(of(neutral, {row["id"]})))
            for row in rows if row["id"] in replayed}
