"""The command map: python -m redteam <command> [arguments], or apertus-redteam once installed.

Each command runs a module or a script that also works on its own (python -m redteam.reproduce,
python3 scripts/build_report.py), with the same arguments and the same --help. Every command runs
in track_1a/, so a relative path in its arguments is read from there.
"""
from __future__ import annotations

import os
import runpy
import sys
from typing import NamedTuple

from .paths import ROOT


class Command(NamedTuple):
    journey: str
    about: str
    steps: list[tuple[str, ...]]  # a module, or a script under track_1a/, then fixed arguments
    takes_arguments: bool = True  # False where the module reads none, so --help cannot start it


AUDIT = [("scripts/report_scorer.py",), ("scripts/report_calibration.py",),
         ("scripts/report_stats.py",), ("scripts/report_stimuli.py",),
         ("crosscheck", "--diffs", "--json", "docs/audit/crosscheck.json"),
         ("scripts/report_rescore.py",)]  # last: it checks what the others wrote
# The runs the report rests on. They come before the caller's arguments, so a flag repeated wins.
REPORT_RUNS = ("--canonical", "20261016-172309-1f71", "--target70", "20261017-140533-a21a",
               "--mitigation", "20261017-144423-5519", "--bank2", "20261017-143329-b04d",
               "--speech", "data/runs/speech/20261017-141121")

CHECK, AUDITS, NEW = "Check the submission", "Audit the numbers and build the report", "New runs"
COMMANDS = {
    "replay": Command(CHECK, "replay the canonical run from data/llm_cache, no GPU",
                      [("redteam.run", "--replay")]),
    "check": Command(CHECK, "validate every findings file against the schema",
                     [("redteam.check",)], False),
    "reproduce": Command(CHECK, "rebuild the five findings from data/runs and compare",
                         [("redteam.reproduce",)]),
    "crosscheck": Command(CHECK, "recount every reported number without the harness",
                          [("crosscheck",)]),
    "audit": Command(AUDITS, "rerun the audit scripts and rewrite docs/audit/", AUDIT, False),
    "figures": Command(AUDITS, "redraw docs/figures/ from the report's runs",
                       [("scripts/report_figures.py", *REPORT_RUNS)]),
    "report": Command(AUDITS, "build Star-rust_Report.pdf (needs Chrome)",
                      [("scripts/build_report.py",)]),
    "dashboard": Command(AUDITS, "dashboard and review page on http://127.0.0.1:8765; "
                         "PORT=8766 for another port", [("redteam.server",)], False),
    "labels": Command(AUDITS, "agreement of the review page's labels with the judge",
                      [("redteam.review",)], False),
    "run": Command(NEW, "a new run: live models if they answer, else replay, else MOCK",
                   [("redteam.run",)]),
    "control": Command(NEW, "ask a run's hypotheses again as neutral questions",
                       [("redteam.control",)]),
    "rejudge": Command(NEW, "a second, independently worded judge on a run",
                       [("redteam.rejudge",)]),
    "learn": Command(NEW, "what each agent learned from the runs and audits, into "
                     "data/agents/roster.json",
                     [("redteam.agent_skills",)]),
}


def usage() -> str:
    lines, journey = ["usage: python -m redteam <command> [arguments]"], None
    for name, command in COMMANDS.items():
        if command.journey != journey:
            journey = command.journey
            lines += ["", journey]
        lines.append(f"  {name:11s} {command.about}")
    lines += ["", "python -m redteam <command> --help shows what a command takes."]
    return "\n".join(lines)


def step(target: str, args: list[str]) -> int:
    """Runs a module or script as its own command line would, and returns its exit status."""
    sys.argv = [target, *args]
    try:
        if target.endswith(".py"):
            if str(ROOT / "scripts") not in sys.path:
                sys.path.insert(0, str(ROOT / "scripts"))  # the scripts import each other by name
            runpy.run_path(str(ROOT / target), run_name="__main__")
        else:
            runpy.run_module(target, run_name="__main__", alter_sys=True)
    except SystemExit as stop:
        if isinstance(stop.code, str):
            print(stop.code, file=sys.stderr)
            return 1
        return stop.code or 0
    return 0


def main(argv: list[str] | None = None) -> int:
    name, *args = (sys.argv[1:] if argv is None else argv) or ["help"]
    if name in ("help", "-h", "--help"):
        print(usage())
        return 0
    command = COMMANDS.get(name)
    if command is None:
        print(f"unknown command: {name}\n\n{usage()}", file=sys.stderr)
        return 2
    if args and not command.takes_arguments:
        runs = "; ".join(" ".join(s) for s in command.steps)
        asked = args in (["-h"], ["--help"])
        print(f"{name}: {command.about}\nruns {runs}, and takes no arguments",
              file=sys.stdout if asked else sys.stderr)
        return 0 if asked else 2
    os.chdir(ROOT)
    for target, *fixed in command.steps:
        status = step(target, fixed + args)
        if status:
            return status
    return 0


if __name__ == "__main__":
    sys.exit(main())
