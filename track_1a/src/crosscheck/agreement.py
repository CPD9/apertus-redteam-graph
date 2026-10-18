"""How far a second, independently worded judge agrees with the main judge's raw flags (before
the severity rule), as Cohen's kappa. Both see the answers as the event log keeps them: the attack
loop's first 600 characters and the verifier's first 3000; the 8B run's log keeps no verifier
answers, so only its attack loop was judged twice."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from redteam.events import read_events

from .checks import Check
from .replies import Replies, second_flag


@dataclass(frozen=True)
class Judged:
    phase: str  # "probe" (attack loop) or "verifier"
    hypothesis: str
    lang: str
    prompt: str
    answer: str
    first: bool  # the main judge's flag as logged


def judged_cells(run_dir: Path) -> list[Judged]:
    prompts, answers, cells = {}, {}, []
    for event in read_events(run_dir / "events.jsonl"):
        hyp, data, step = event["hypothesis"], event["data"], (event["node"], event["status"])
        if step == ("mutator", "done"):
            prompts[hyp] = data["prompts"]
        elif step == ("target", "done"):
            answers[hyp, data["lang"]] = data["answer"]
        elif step == ("judge", "done"):
            lang = data["lang"]
            cells.append(Judged("probe", hyp, lang, prompts[hyp][lang], answers[hyp, lang],
                                data["violation"]))
        elif step == ("verifier", "progress") and "answer" in data:
            lang = data["lang"]
            cells.append(Judged("verifier", hyp, lang, prompts[hyp][lang], data["answer"],
                                data["violation"]))
    return cells


def kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    """Cohen's kappa of two yes/no raters; None when chance alone gives full agreement."""
    n = len(pairs)
    if not n:
        return None
    observed = sum(a == b for a, b in pairs) / n
    first, second = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    chance = first * second + (1 - first) * (1 - second)
    return None if chance == 1 else (observed - chance) / (1 - chance)


@dataclass
class Agreement:
    cells: list[Judged]
    second: list[bool]

    @property
    def pairs(self) -> list[tuple[bool, bool]]:
        return [(c.first, s) for c, s in zip(self.cells, self.second)]

    def phase(self, name: str) -> int:
        return sum(c.phase == name for c in self.cells)

    @property
    def raw(self) -> float:
        return sum(a == b for a, b in self.pairs) / len(self.pairs)


def agreement(run_dir: Path, judge: str, refs: dict[str, dict], replies: Replies) -> Agreement:
    cells = [c for c in judged_cells(run_dir) if c.hypothesis in refs]
    second = [second_flag(replies.premise(judge, refs[c.hypothesis]["reference"], c.prompt,
                                          c.answer)) for c in cells]
    return Agreement(cells, second)


def rejudge_checks(at: str, stated: dict, mine: Agreement) -> list[Check]:
    pairs = [(c["first"], c["second"]) for c in stated.get("cells", [])]
    differing = sum(a != b for a, b in zip(pairs, mine.pairs)) + abs(len(pairs) - len(mine.pairs))
    return [Check(f"{at} n", stated.get("n"), len(mine.pairs)),
            Check(f"{at} cells whose (first, second) differ from the replay", 0, differing),
            Check(f"{at} kappa", stated.get("kappa"), kappa(mine.pairs), 1e-9),
            Check(f"{at} raw_agreement", stated.get("raw_agreement"), mine.raw, 1e-9)]
