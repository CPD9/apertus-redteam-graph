"""Re-derive every value the report and the findings state from the recorded data and print a
summary, each value as source | expected | recomputed | OK or DIFF section by section, then the
differences; exit 1 on any difference.

    PYTHONPATH=src python3 -m crosscheck [--diffs] [--json PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from redteam import paths

from .audit import RUNS, SPEECH_RUN, load, replayed
from .bounds import CI, HARNESS_DRAWS, LARGEST, SLACK
from .rates import DRAWS, SEED
from .sections import NOT_COVERED, all_checks


def tallied(checks) -> dict[str, int]:
    return {"checked": len(checks), "numeric": sum(c.numeric for c in checks),
            "design constants": sum(c.constant for c in checks),
            "2000-draw estimates off the exact quantile": sum(c.estimated for c in checks),
            "differ": sum(not c.ok for c in checks)}


def per_section(sections: dict[str, list]) -> dict[str, dict[str, int]]:
    return {name: {"checked": len(found), "differ": sum(not c.ok for c in found)}
            for name, found in sections.items()}


def summary(counts: dict[str, int], parts: dict[str, dict], replay: dict) -> list[str]:
    judge, verified = replay["judge replies"], replay["verified answers"]
    width = max(map(len, [*parts, "section"]))
    return [
        f"{counts['checked']} checks against the recorded runs: {counts['differ']} differ.",
        "",
        f"{'section':<{width}}  checks  differ",
        *(f"{name:<{width}}  {part['checked']:>6}  {part['differ']:>6}"
          for name, part in parts.items()),
        "",
        f"{counts['numeric']} compare numbers and {counts['design constants']} compare against "
        f"design constants; {counts['2000-draw estimates off the exact quantile']} agree as "
        "2000-draw estimates off the exact quantile.",
        f"Replayed {sum(verified.values())} verified answers "
        f"({', '.join(map(str, verified.values()))}), {replay['neutral answers']} neutral, "
        f"{sum(replay['second-judge verdicts'].values())} second-judge; of "
        f"{judge.get('judge replies', 0)} judge replies {judge.get('took the repair turn', 0)} "
        f"took the repair turn and {judge.get('then read leniently', 0)} then read leniently.",
    ]


def written(path: Path, counts: dict[str, int], parts: dict[str, dict], replay: dict,
            checks: list) -> None:
    out = {"runs": RUNS, "speech_run": SPEECH_RUN,
           "bootstrap": {"enumerated up to resamples": LARGEST, "harness draws": HARNESS_DRAWS,
                         "cdf slack": round(SLACK, 4), "redrawn": DRAWS, "seed": SEED,
                         "redrawn tolerance": CI},
           **counts, "sections": parts, "replay": replay,
           "checks": [c.record() for c in checks],
           "not_covered": [{"what": what, "why": why} for what, why in NOT_COVERED]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    about = " ".join(__doc__.split("\n\n")[0].split())
    ap = argparse.ArgumentParser(prog="python3 -m crosscheck", description=about)
    ap.add_argument("--diffs", action="store_true", help="print the summary and differences only")
    ap.add_argument("--json", type=Path, help="also write every check and what is not covered")
    args = ap.parse_args(argv)
    audit = load(paths.ROOT)
    sections = all_checks(audit, paths.ROOT)
    checks = [c for found in sections.values() for c in found]
    counts, parts, replay = tallied(checks), per_section(sections), replayed(audit)
    print("\n".join(summary(counts, parts, replay)))
    if not args.diffs:
        for name, found in sections.items():
            print(f"\n== {name} ==", *(c.line() for c in found), sep="\n")
        print("\nNot re-derived:", *(f"- {what}: {why}" for what, why in NOT_COVERED), sep="\n")
    print("\nDifferences:", *([c.line() for c in checks if not c.ok] or ["none"]), sep="\n")
    print(f"\n{counts['checked']} checks, {counts['differ']} differ")
    if args.json:
        written(args.json, counts, parts, replay, checks)
    return 1 if counts["differ"] else 0


if __name__ == "__main__":
    sys.exit(main())
