"""What one recorded run says about each agent of the graph, read without asking any model: the
event log for what the agents did, and the LLM cache for the judge's full verdicts on the verified
answers (answers.load_run), which the log keeps only as a flag."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import answers, paths
from .agents import LANG_NAMES, counts
from .events import read_events
from .graph import Config
from .shares import Share, per_lang, share

AUDIT = paths.ROOT / "docs" / "audit"


@dataclass
class Strategy:
    attempts: int = 0
    landed: int = 0      # attempts with at least one probe answer that counts
    verified: int = 0    # attempts the judge flagged, so the verifier took the hypothesis on
    reproduced: int = 0  # of those, hypotheses whose counted share reached the bar


@dataclass
class RunFacts:
    id: str
    source: str  # the event log, relative to track_1a/
    label: str
    model: str
    backend: str
    system: bool  # whether the target had a system prompt (the mitigation runs)
    langs: list[str]
    ids: list[str] = field(default_factory=list)  # the hypotheses, in the run's order
    hypotheses: int = 0
    tested: int = 0  # hypotheses the verifier took on
    seeds: list[int] = field(default_factory=list)
    strategies: dict[str, Strategy] = field(default_factory=dict)
    prompts: int = 0  # translations the mutator wrote
    language_check: dict[str, Share] = field(default_factory=dict)  # named as the asked language
    flagged: int = 0  # verified answers the judge flagged
    counted: Share = Share(0, 0)  # verified answers that count, over those replayed
    per_lang: dict[str, Share] = field(default_factory=dict)
    unreplayed: list[str] = field(default_factory=list)
    reproduced: int = 0
    findings: int = 0  # findings files the scribe wrote

    @property
    def date(self) -> str:
        day = self.id[:8]
        return f"{day[:4]}-{day[4:6]}-{day[6:]}" if day.isdigit() else ""

    @property
    def name(self) -> str:
        size = "70B" if "70B" in self.model else "8B" if "8B" in self.model else self.model
        return f"{self.label or size} run {self.id}"


def run_facts(run_dir: Path, refs: dict[str, dict]) -> RunFacts:
    """Everything the agents did in one run. Raises ValueError for a log without a start event."""
    events = read_events(run_dir / "events.jsonl")
    if not events or (events[0]["node"], events[0]["status"]) != ("graph", "start"):
        raise ValueError(f"{run_dir.name} has no start event")
    start = events[0]
    facts = RunFacts(id=run_dir.name, source=str(source(run_dir / "events.jsonl")),
                     label=start["data"].get("label") or "", model=start["model"],
                     backend=start["backend"], system=bool(start["data"].get("system")),
                     langs=start["data"].get("langs", []))
    attempt, strategy, landed = {}, {}, set()
    for event in events:
        hyp, data, step = event["hypothesis"], event["data"], (event["node"], event["status"])
        if step == ("attacker", "start"):
            attempt[hyp] = data.get("attempt", 1)
        elif step == ("attacker", "done"):
            strategy[hyp] = facts.strategies.setdefault(data.get("strategy", "unnamed"), Strategy())
            strategy[hyp].attempts += 1
        elif step == ("mutator", "done"):
            facts.prompts += len(data.get("prompts", {}))
            for lang, named in data.get("detected", {}).items():
                was, right = facts.language_check.get(lang, Share(0, 0)), LANG_NAMES.get(lang)
                facts.language_check[lang] = Share(was.k + (named == right), was.n + 1)
        elif step == ("judge", "done"):
            if counts(data["violation"], data.get("severity", 0)) and hyp in strategy \
                    and (hyp, attempt.get(hyp)) not in landed:
                landed.add((hyp, attempt.get(hyp)))
                strategy[hyp].landed += 1
        elif step == ("verifier", "start"):
            facts.seeds = data.get("seeds", facts.seeds)
            if hyp in strategy:
                strategy[hyp].verified += 1
        elif step == ("scribe", "done") and data.get("path"):
            facts.findings += 1
    replayed = answers.load_run(run_dir, refs, answers.CACHE_DIR, partial=True)
    facts.ids, facts.unreplayed = replayed.hypotheses, replayed.unreplayed
    facts.hypotheses = len(replayed.hypotheses)
    facts.flagged = sum(a.flagged for a in replayed.answers)
    facts.counted, facts.per_lang = share(replayed.answers), per_lang(replayed.answers, facts.langs)
    by_hypothesis: dict[str, list] = {}
    for a in replayed.answers:
        by_hypothesis.setdefault(a.hypothesis, []).append(a)
    facts.tested = len(by_hypothesis)
    for hyp, cells in by_hypothesis.items():
        if share(cells).rate >= Config.min_rate:
            facts.reproduced += 1
            if hyp in strategy:
                strategy[hyp].reproduced += 1
    return facts


def source(path: Path) -> Path:
    """A file as the roster names it: relative to track_1a/ when it lies inside it."""
    return path.relative_to(paths.ROOT) if path.is_relative_to(paths.ROOT) else path


def audit(name: str) -> dict | None:
    """docs/audit/<name>.json, or None when that audit has not been run."""
    path = AUDIT / f"{name}.json"
    return json.loads(path.read_text()) if path.is_file() else None


def dig(data, *keys):
    """data[k1][k2]..., or None where a key is missing (an audit from an older script)."""
    for key in keys:
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def of(k: int, n: int, what: str = "") -> str:
    """A count with its denominator, the form every value in the roster takes."""
    share = f" ({k / n:.0%})" if n else ""
    return f"{k} of {n}{' ' + what if what else ''}{share}"


def strength(kappa: float) -> str:
    """The usual words for a kappa (Landis and Koch)."""
    words = [(0.2, "slightly"), (0.4, "fairly"), (0.6, "moderately"), (0.8, "substantially")]
    return next((word for bound, word in words if kappa < bound), "almost perfectly")


def evidence(label: str, value: str, source: Path | str) -> dict:
    return {"label": label, "value": value, "source": str(source)}


def skill(id: str, name: str, summary: str, proof: list[dict], learned_from: str,
          since: str = "") -> dict:
    """A skill of an agent; since is filled in by the roster when it is learned from an audit."""
    return {"id": id, "name": name, "summary": summary, "evidence": proof,
            "learned_from": learned_from, "since": since}


def learning(text: str, proof: list[dict], source: str, since: str = "") -> dict:
    return {"text": text, "evidence": proof, "source": source, "since": since}
