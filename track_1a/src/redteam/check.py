"""Validate the submitted findings (findings/*.json, at most five) and those of the latest local
run against findings/findings.schema."""
import json
import sys
from pathlib import Path

from . import paths
from .scribe import validate

FINDINGS = paths.ROOT / "findings"
MAX_SUBMITTED = 5  # the case accepts up to five findings files


def files() -> tuple[list[Path], list[Path]]:
    """The submitted findings files, and the files the latest local run wrote."""
    latest = paths.run_dir("latest")
    run = sorted((latest / "findings").glob("*.json")) if latest else []
    return sorted(FINDINGS.glob("*.json")), run


def report(path: Path) -> bool:
    errors = validate(json.loads(path.read_text()))
    name = path.relative_to(paths.ROOT) if path.is_relative_to(paths.ROOT) else path
    print(("FAIL " if errors else "OK   ") + str(name), *errors, sep="\n     ")
    return not errors


def main() -> int:
    submitted, run = files()
    valid = [report(path) for path in submitted + run]
    print(f"{sum(valid)}/{len(valid)} findings files valid")
    if len(submitted) > MAX_SUBMITTED:
        print(f"FAIL {len(submitted)} findings files in findings/, at most {MAX_SUBMITTED} allowed")
    return 0 if all(valid) and len(submitted) <= MAX_SUBMITTED else 1


if __name__ == "__main__":
    sys.exit(main())
