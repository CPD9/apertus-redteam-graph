"""Print every value the report and the findings state next to the value re-derived from the
recorded data; exit 1 on any difference.

    PYTHONPATH=src python3 -m crosscheck [--diffs] [--json PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from redteam import paths

from .audit import RUNS, SPEECH_RUN, load, replayed
from .bounds import CI, HARNESS_DRAWS, SLACK
from .exact import LARGEST
from .rates import DRAWS, SEED
from .sections import all_checks
from .uncovered import NOT_COVERED


def tallied(checks) -> dict[str, int]:
    return {"checked": len(checks), "numeric": sum(c.numeric for c in checks),
            "design constants": sum(c.constant for c in checks),
            "2000-draw estimates off the exact quantile": sum(c.estimated for c in checks),
            "differ": sum(not c.ok for c in checks)}


def written(checks, replay: dict, path: Path) -> None:
    out = {"runs": RUNS, "speech_run": SPEECH_RUN,
           "bootstrap": {"enumerated up to resamples": LARGEST, "harness draws": HARNESS_DRAWS,
                         "cdf slack": round(SLACK, 4), "redrawn": DRAWS, "seed": SEED,
                         "redrawn tolerance": CI},
           **tallied(checks), "replay": replay,
           "checks": [c.record() for c in checks],
           "not_covered": [{"what": what, "why": why} for what, why in NOT_COVERED]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


def summary(counts: dict[str, int], replay: dict) -> str:
    judge = replay["judge replies"]
    verified = replay["verified answers"]
    return (f"Replayed {sum(verified.values())} verified answers "
            f"({', '.join(map(str, verified.values()))}), {replay['neutral answers']} neutral, "
            f"{sum(replay['second-judge verdicts'].values())} second-judge; of "
            f"{judge.get('judge replies', 0)} judge replies {judge.get('took the repair turn', 0)} "
            f"took the repair turn and {judge.get('then read leniently', 0)} then read leniently."
            f"\n{counts['checked']} checks ({counts['numeric']} numeric, "
            f"{counts['design constants']} against design constants), {counts['differ']} differ; "
            f"{counts['2000-draw estimates off the exact quantile']} agree as 2000-draw estimates "
            "off the exact quantile")


def main(argv=None) -> int:
    about = " ".join(__doc__.split("\n\n")[0].split())
    ap = argparse.ArgumentParser(prog="python3 -m crosscheck", description=about)
    ap.add_argument("--diffs", action="store_true", help="print only the values that differ")
    ap.add_argument("--json", type=Path, help="also write every check and what is not covered")
    args = ap.parse_args(argv)
    audit = load(paths.ROOT)
    checks = all_checks(audit, paths.ROOT)
    for check in checks:
        if not (args.diffs and check.ok):
            print(check.line())
    print("\nNot re-derived:")
    for what, why in NOT_COVERED:
        print(f"- {what}: {why}")
    counts, replay = tallied(checks), replayed(audit)
    print("\n" + summary(counts, replay))
    if args.json:
        written(checks, replay, args.json)
    return 1 if counts["differ"] else 0


if __name__ == "__main__":
    sys.exit(main())
