"""The agents as characters, with the skills and learnings that the recorded runs and the audits
give them.

    python -m redteam learn [--run ID ...]

rewrites data/agents/roster.json from the report's four runs and docs/audit/ (agent_lessons). The
name, role, intro and colour of each character are written by hand in data/agents/characters.json.
A run given with --run, one made since, adds to the skills and adds what changed against the
closest recorded run, dated; a later learn keeps every run the roster has learned from.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import paths, reproduce
from .agent_facts import RunFacts, audit, dig, evidence, learning, of, run_facts, skill, source
from .agent_lessons import MINERS
from .run import load_hypotheses

AGENTS = paths.ROOT / "data" / "agents"
CHARACTERS, ROSTER = AGENTS / "characters.json", AGENTS / "roster.json"
# The runs the report rests on, oldest first: 8B, 70B, 70B on bank 2, 70B with a system prompt.
RECORDED = ["20261016-172309-1f71", "20261017-140533-a21a", "20261017-143329-b04d",
            "20261017-144423-5519"]
RUN_ID = re.compile(r"\d{8}-\d{6}-\w+")
CROSSCHECK = "docs/audit/crosscheck.json"


def located(run_id: str) -> Path | None:
    """A run's folder: the copy shipped in data/runs/ for a recorded run, so the roster names
    files a fresh checkout has; otherwise where redteam.paths finds it."""
    shipped = paths.SHIPPED / run_id
    return shipped if (shipped / "events.jsonl").is_file() else paths.run_dir(run_id)


def audits(runs: list[RunFacts]) -> dict:
    found = {name: audit(name) for name in ("calibration", "scorer", "stimuli", "stats",
                                            "crosscheck")}
    found = {name: data for name, data in found.items() if data}
    seconds = {r.id: paths.ROOT / Path(r.source).parent / "rejudge.json" for r in runs}
    found["rejudge"] = {i: json.loads(p.read_text()) for i, p in seconds.items() if p.is_file()}
    return found


def rebuilt() -> dict[str, list[str]]:
    """Each findings file rebuilt from the recorded runs: how it differs, by name."""
    findings = {p.stem: p.read_text() for p in sorted(reproduce.FINDINGS.glob("*.json"))}
    return {name: lines for name, (_, lines) in reproduce.check(findings).items()}


def scribe(runs: list[RunFacts], audits: dict) -> tuple[list, list]:
    skills = [skill("writes-findings", "Writes the findings",
                    "Writes a findings file for each hypothesis the verifier passes, with every "
                    "prompt, answer and rate it rests on.",
                    [evidence(r.name, f"{r.findings} files written at the run's flag bar; "
                              f"{of(r.reproduced, r.hypotheses, 'hypotheses')} reproduce under "
                              "the counting rule", r.source) for r in runs],
                    runs[0].id, runs[0].date)]
    if rebuilt := audits.get("rebuilt"):
        differ = [f"findings/{name}.json" for name, lines in rebuilt.items() if lines]
        skills.append(skill(
            "rebuilds-identically", "Every finding rebuilds",
            "Each findings file is rebuilt from the recorded runs and compared character by "
            "character (python -m redteam reproduce).",
            [evidence("rebuilt identically", of(len(rebuilt) - len(differ), len(rebuilt), "files"),
                      "findings/")]
            + [evidence("differs from its rebuild", name, name) for name in differ], "findings/"))
    learnings = []
    if sections := dig(audits.get("crosscheck"), "sections"):
        cc = audits["crosscheck"]
        learnings.append(learning(
            f"A recount written apart from the harness checked {cc['checked']} numbers in my "
            f"findings, the figures and the report, and {cc['differ']} differ.",
            [evidence(name, of(s["differ"], s["checked"], "numbers differ"), CROSSCHECK)
             for name, s in sections.items()], CROSSCHECK))
    return skills, learnings


EVERY = {**MINERS, "scribe": scribe}


def closest(new: RunFacts, runs: list[RunFacts]) -> RunFacts:
    """The recorded run a new one is compared with: same model and system prompt, then the most
    hypotheses in common."""
    alike = [r for r in runs if r.model == new.model and r.system == new.system] or runs
    return max(alike, key=lambda r: len(set(r.ids) & set(new.ids)))


def checked(r: RunFacts) -> str:
    named = r.language_check.values()
    return of(sum(s.k for s in named), sum(s.n for s in named), "translations named as asked")


MEASURES = {  # what each agent compares between a new run and the closest recorded one
    "attacker": ("taken to the verifier", lambda r: of(
        sum(s.verified for s in r.strategies.values()), r.hypotheses, "hypotheses")),
    "mutator": ("the language check", checked),
    "target": ("answers that count", lambda r: of(r.counted.k, r.counted.n, "answers")),
    "judge": ("flagged answers I rated 0", lambda r: of(
        r.flagged - r.counted.k, r.flagged, "flagged answers")),
    "verifier": ("reproduced", lambda r: of(r.reproduced, r.hypotheses, "hypotheses")),
    "scribe": ("findings files written", lambda r: of(r.findings, r.hypotheses, "hypotheses")),
}


def changes(new: RunFacts, runs: list[RunFacts]) -> dict[str, list[dict]]:
    """What a run made since tells each agent, set against the closest recorded run."""
    if new.backend == "MOCK":
        return {"verifier": [learning(
            f"{new.date}, {new.name} used the MOCK backend: its answers are not Apertus's, so I "
            "learned nothing about the model from it.",
            [evidence("backend", new.backend, new.source)], new.id, new.date)]}
    was = closest(new, runs)
    out = {}
    for agent, (what, measure) in MEASURES.items():
        now, before = measure(new), measure(was)
        out[agent] = [learning(f"{new.date}, {new.name}: {what}: {now}; in the {was.name}: "
                               f"{before}.", [evidence(new.name, now, new.source),
                                              evidence(was.name, before, was.source)],
                               new.id, new.date)]
    if new.unreplayed:
        out["verifier"].append(learning(
            f"{new.date}, {new.name}: {of(len(new.unreplayed), new.hypotheses, 'hypotheses')} "
            "could not be replayed from data/llm_cache, so the shares above leave them out.",
            [evidence("not replayed", ", ".join(new.unreplayed), new.source)], new.id, new.date))
    return out


def roster(characters: list[dict], runs: list[RunFacts], new: list[RunFacts], found: dict,
           previous: list[dict], today: str) -> list[dict]:
    """Every character with its skills and learnings. A skill or learning learned from an audit
    keeps the date of the first roster that had it."""
    first = {(a["id"], item.get("id") or item.get("text")): item.get("since")
             for a in previous for item in [*a.get("skills", []), *a.get("learnings", [])]}
    # A replay repeats a recorded run and MOCK is not Apertus: both only add a dated note.
    real = sorted([*runs, *(r for r in new if r.backend not in ("MOCK", "replay"))],
                  key=lambda r: r.id)
    noted = [changes(r, runs) for r in new]
    out = []
    for c in characters:
        skills, learnings = EVERY[c["id"]](real, found)
        learnings += [item for n in noted for item in n.get(c["id"], [])]
        for item in [*skills, *learnings]:
            item["since"] = item["since"] or first.get((c["id"], item.get("id") or item["text"])) \
                or today
        out.append({"id": c["id"], "name": c["name"], "role": c["role"],
                    "avatar": f"avatars/{c['id']}.png", "color": c["color"], "intro": c["intro"],
                    "skills": skills, "learnings": learnings})
    return out


def remembered(previous: list[dict]) -> list[str]:
    """The runs made since that an earlier roster learned from."""
    named = {item.get("learned_from") or item.get("source") or "" for a in previous
             for item in [*a.get("skills", []), *a.get("learnings", [])]}
    return sorted(i for i in named if RUN_ID.fullmatch(i) and i not in RECORDED)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Recompute what each agent can do and has learned "
                                 "from the recorded runs and audits, into data/agents/roster.json.")
    ap.add_argument("--run", nargs="+", default=[], metavar="ID",
                    help="runs made since to learn from too: an id, or latest")
    a = ap.parse_args(argv)
    if missing := [i for i in [*RECORDED, *a.run] if located(i) is None]:
        ap.error(f"no run {', '.join(missing)} in runs/ or data/runs/")
    previous = json.loads(ROSTER.read_text()) if ROSTER.is_file() else []
    asked = [located(i).name for i in a.run]  # latest becomes the id it stands for
    since = [i for i in dict.fromkeys([*asked, *remembered(previous)])
             if i not in RECORDED and located(i)]
    refs = {h["id"]: h for h in load_hypotheses()}
    try:
        runs = [run_facts(located(i), refs) for i in RECORDED]
        new = [run_facts(located(i), refs) for i in since]
    except ValueError as e:
        ap.error(str(e))
    found = {**audits(runs + new), "rebuilt": rebuilt()}
    out = roster(json.loads(CHARACTERS.read_text()), runs, new, found, previous,
                 date.today().isoformat())
    ROSTER.parent.mkdir(parents=True, exist_ok=True)
    ROSTER.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    for agent in out:
        print(f"  {agent['id']:9s} {len(agent['skills'])} skills, "
              f"{len(agent['learnings'])} learnings")
    print(f"learned from {len(runs) + len(new)} runs and the audits: {source(ROSTER)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
