"""Validate every findings file (submission + latest run) against findings/findings.schema."""
import json
import sys
from pathlib import Path

from .scribe import validate

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    files = [p for p in (ROOT / "findings").glob("*.json") if p.name != "example_findings.json"]
    latest = ROOT / "runs" / "latest"
    if latest.exists():
        files += sorted((ROOT / "runs" / latest.read_text().strip() / "findings").glob("*.json"))
    bad = 0
    for f in files:
        errs = validate(json.loads(f.read_text()))
        print(("OK   " if not errs else "FAIL ") + str(f.relative_to(ROOT)), *errs, sep="\n     " if errs else "")
        bad += bool(errs)
    print(f"{len(files) - bad}/{len(files)} findings files valid")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
