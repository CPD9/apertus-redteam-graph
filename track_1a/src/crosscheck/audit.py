"""The recorded data measured once: every run replayed, the canonical run's neutral control, the
four themes, the two run comparisons, the speech clips and the judge agreement."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from redteam.cache import PACK

from .agreement import Agreement, agreement
from .compare import Comparison, compare
from .replies import Replies
from .runs import Run, Verdict, neutral, read
from .speech import Speech
from .themes import Theme, measure

# The recorded runs the report and the findings rest on.
RUNS = {"canonical": "20261016-172309-1f71", "target70": "20261017-140533-a21a",
        "mitigation": "20261017-144423-5519", "bank2": "20261017-143329-b04d"}
SPEECH_RUN = "20261017-141121"
BANKS = ("bank", "core", "bank2")
MITIGATION_NAMES = ["No system prompt", "Mitigation system prompt"]


@dataclass
class Audit:
    banks: dict[str, list[dict]]
    refs: dict[str, dict]  # every hypothesis of the banks, by id
    themes_spec: list[dict]
    runs: dict[str, Run]
    neutral: list[Verdict]
    neutral_unreplayed: list[str]
    themes: dict[str, Theme]
    size: Comparison
    mitigation: Comparison
    speech: Speech
    agreement: dict[str, Agreement]
    tally: dict[str, int]  # how the judge replies read
    read_as: set[tuple]  # (run, hypothesis, lang, seed) the word list reads as the pair language

    @property
    def titles(self) -> dict[str, str]:
        return {h: ref.get("title", h) for h, ref in self.refs.items()}


def read_json(path: Path):
    return json.loads(path.read_text())


def load(root: Path) -> Audit:
    """root is track_1a/: data/runs, data/llm_cache, src/redteam's banks and themes.json, and the
    answers docs/audit/stimuli.json reads as Standard German or Italian."""
    source = root / "src" / "redteam"
    banks = {name: read_json(source / "hypotheses" / f"{name}.json") for name in BANKS}
    refs = {h["id"]: h for bank in banks.values() for h in bank}
    replies = Replies.read(root / "data" / "llm_cache" / PACK)
    shipped = root / "data" / "runs"
    runs = {name: read(shipped / run_id, refs, replies) for name, run_id in RUNS.items()}
    canonical = runs["canonical"]
    rows = read_json(shipped / canonical.id / "control.json")
    verdicts, unreplayed = neutral(rows, canonical, refs, replies)
    specs = read_json(source / "themes.json")
    themes = {spec["id"]: theme for spec in specs
              if (theme := measure(spec, canonical, verdicts, runs["target70"]))}
    agreements = {name: agreement(shipped / runs[name].id, runs[name].judge, refs, replies)
                  for name in ("canonical", "target70")}
    sizes = [run.model.rsplit("/", 1)[-1] for run in (canonical, runs["target70"])]
    listed = read_json(root / "docs" / "audit" / "stimuli.json")["answers_listed"]
    return Audit(banks, refs, specs, runs, verdicts, unreplayed, themes,
                 compare(canonical, runs["target70"], sizes),
                 compare(runs["target70"], runs["mitigation"], MITIGATION_NAMES),
                 Speech(read_json(shipped / "speech" / SPEECH_RUN / "scores.json")), agreements,
                 dict(replies.tally),
                 {(a["run"], a["hypothesis"], a["lang"], a["seed"]) for a in listed})


def replayed(audit: Audit) -> dict:
    """What the replay found in the cache, for the audit note to cite."""
    return {"verified answers": {name: len(run.verdicts) for name, run in audit.runs.items()},
            "neutral answers": len(audit.neutral),
            "second-judge verdicts": {name: len(a.pairs) for name, a in audit.agreement.items()},
            "judge replies": audit.tally}
