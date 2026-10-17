"""Rebuild the five findings from the recorded runs and fail on any difference with findings/.

    PYTHONPATH=src python3 -m redteam.reproduce

The four themed findings are rebuilt with redteam.group from the runs each one names, found by
redteam.paths (data/runs/ is enough), with every answer and verdict replayed from data/llm_cache.
The speech finding is rebuilt with redteam.speech_finding from data/runs/speech/<run>/scores.json
(redteam.speech_scores): SwissDial (CC BY-NC 4.0) is not redistributed, so the model outputs it
quotes are the one part taken from the finding as written. When everything matches, the summary
table of the technical report is printed from the findings.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys

from . import group, paths, report_table, speech_finding, speech_scores

FINDINGS = paths.ROOT / "findings"
SPEECH = speech_finding.FINDING.stem
CONTEXT = 60  # characters shown on each side of where two texts first differ


def runs_of(finding: dict) -> tuple[str, ...]:
    """The redteam.group arguments that rebuild a themed finding: the runs it names."""
    p = finding["model"]["parameters"]
    args = ("--run", p["harness_run_id"])
    for flag, key in (("--control", "harness_control"), ("--replication", "harness_replication")):
        args += (flag, p[key]["run_id"]) if key in p else ()
    return args


def grouped(args: tuple[str, ...], theme_ids: list[str]) -> dict[str, dict]:
    """The findings redteam.group builds from these runs. Raises ValueError saying why it cannot."""
    missing = [run_id for run_id in dict.fromkeys(args[1::2]) if paths.run_dir(run_id) is None]
    if missing:
        raise ValueError(f"no run {', '.join(missing)} in runs/ or data/runs/")
    errors = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
            return group.main([*args, "--themes", *theme_ids])  # it prints its own table
    except SystemExit:  # group reports a missing control or cache entry as a usage error
        raise ValueError(errors.getvalue().strip().partition(": error: ")[2]) from None


def rebuild(themed: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """Each themed finding as redteam.group builds it now, written to nothing; and for those it
    cannot build, why."""
    by_runs: dict[tuple[str, ...], list[str]] = {}
    for theme_id, finding in themed.items():
        by_runs.setdefault(runs_of(finding), []).append(theme_id)
    rebuilt, unbuilt = {}, {}
    for args, theme_ids in by_runs.items():
        try:
            rebuilt |= grouped(args, theme_ids)
        except ValueError as e:
            unbuilt |= dict.fromkeys(theme_ids, str(e))
    return rebuilt, unbuilt


def excerpt(value, other) -> str:
    """A value as JSON; of two texts, the part around where they first differ."""
    if not (isinstance(value, str) and isinstance(other, str)):
        return json.dumps(value, ensure_ascii=False)
    at = next((i for i, (a, b) in enumerate(zip(value, other)) if a != b),
              min(len(value), len(other)))
    start, end = max(0, at - CONTEXT), at + CONTEXT
    text = json.dumps(value[start:end], ensure_ascii=False)
    return ("..." if start else "") + text + ("..." if end < len(value) else "")


def differences(want, got, where: str = "") -> list[str]:
    """Where two JSON values differ, the one in findings/ first and the rebuilt one second."""
    if isinstance(want, dict) and isinstance(got, dict):
        lines = []
        for key in dict.fromkeys([*want, *got]):
            here = f"{where}.{key}" if where else key
            if key not in got or key not in want:
                lines.append(f"{here}: only in {'findings/' if key in want else 'the rebuild'}")
            else:
                lines += differences(want[key], got[key], here)
        return lines
    if isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            return [f"{where}: length {len(want)} in findings/, {len(got)} in the rebuild"]
        return [line for i, (a, b) in enumerate(zip(want, got))
                for line in differences(a, b, f"{where}[{i}]")]
    if want == got:
        return []
    return [f"{where or 'file'}:", f"  findings/ {excerpt(want, got)}",
            f"  rebuilt   {excerpt(got, want)}"]


def compared(text: str, rebuilt: dict | None) -> list[str]:
    """How a findings file differs from its rebuild, formatting included."""
    if rebuilt is None:
        return ["the rebuild has no such finding: none of its variations reproduces"]
    written = json.dumps(rebuilt, indent=2, ensure_ascii=False) + "\n"
    if text == written:
        return []
    return (differences(json.loads(text), json.loads(written))
            or ["same content, written differently: rewrite it with its generator's --write"])


def speech_check(text: str) -> tuple[str, list[str]]:
    finding = json.loads(text)
    scores = speech_scores.path_of(finding["model"]["parameters"]["harness_run_id"])
    name = scores.relative_to(paths.ROOT)
    source = f"its rebuild from {name}"
    if not scores.is_file():
        return source, [f"cannot rebuild it: {name} does not exist"]
    try:
        return source, compared(text, speech_scores.rebuild(finding))
    except KeyError as e:  # scores.json is older than what speech_finding.build reads
        return source, [f"cannot rebuild it: {name} has no {e}"]
    except ValueError as e:  # the rebuild does not match the schema
        return source, [f"cannot rebuild it: {e}"]


def check(findings: dict[str, str]) -> dict[str, tuple[str, list[str]]]:
    """For each findings file by name: what it was checked against, and how it differs."""
    themes = [t["id"] for t in group.THEMES]
    rebuilt, unbuilt = rebuild({name: json.loads(text) for name, text in findings.items()
                                if name in themes})
    checked = {name: ("the findings this repository builds", ["the file is missing"])
               for name in [*themes, SPEECH] if name not in findings}
    for name, text in findings.items():
        if name in unbuilt:
            checked[name] = ("its rebuild", [f"cannot rebuild it: {unbuilt[name]}"])
        elif name in themes:
            checked[name] = ("its rebuild", compared(text, rebuilt.get(name)))
        elif name == SPEECH:
            checked[name] = speech_check(text)
        else:
            checked[name] = ("the findings this repository builds", ["no generator writes it"])
    return checked


def in_report_order(findings: dict[str, str]) -> list[dict]:
    order = [t["id"] for t in group.THEMES] + [SPEECH]
    return [json.loads(findings[name]) for name in order if name in findings]


def main(argv=None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    findings = {path.stem: path.read_text() for path in sorted(FINDINGS.glob("*.json"))}
    checked = check(findings)
    for name, (source, lines) in checked.items():
        verdict = f"differs from {source}:" if lines else f"matches {source}"
        print(f"findings/{name}.json {verdict}", *(f"  {line}" for line in lines), sep="\n")
    if any(lines for _, lines in checked.values()):
        return 1
    try:
        print(report_table.table(in_report_order(findings)))
    except ValueError as e:
        print(f"the summary table cannot be printed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
