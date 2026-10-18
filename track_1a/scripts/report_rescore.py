"""Writes docs/audit/rescore.md from docs/audit/rescore.json, the re-scoring of the submitted
findings against the rubric, after checking that every value, answer count and claim the JSON
cites still holds (scripts/report_rescore_check.py). On any mismatch it lists them all and
writes nothing.

    cd track_1a && python3 scripts/report_rescore.py           # check, then write the note
    cd track_1a && python3 scripts/report_rescore.py --check   # check only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # without pip install -e

from report_note import grid_table, spelled  # noqa: E402
from report_rescore_check import CATEGORIES, TRACK, problems  # noqa: E402

AUDIT = TRACK / "docs" / "audit"
NAMES = {"severity": "Severity", "breadth": "Breadth", "novelty": "Novelty",
         "validity": "Validity"}


def shown(score) -> str:
    return "–" if score is None else str(score)


def cell(text: str) -> str:
    return text.replace("|", "\\|")


def points(entry: dict) -> int:
    return sum(entry["scores"][c]["supported"] for c in CATEGORIES)


def summary(rescore: dict) -> list[str]:
    rows = []
    for number, entry in enumerate(rescore["findings"], 1):
        scores = entry["scores"]
        rows.append([f"{number}. {entry['name']}",
                     *(f"{shown(scores[c]['self'])} → {scores[c]['supported']}"
                       for c in CATEGORIES), str(points(entry))])
    total = sum(points(entry) for entry in rescore["findings"])
    stated, supported = (sum(entry["scores"][c][side] for entry in rescore["findings"]
                             for c in ("severity", "breadth")) for side in ("self", "supported"))
    floor = all(entry["scores"][c]["supported"] >= 1
                for entry in rescore["findings"] for c in CATEGORIES)
    return [
        "## Scores", "",
        "Each cell gives the self-score in the finding, then the score the evidence supports; – "
        "means the finding has no self-score, as the schema has fields for severity and breadth "
        "only. Points add the four supported scores.", "",
        *grid_table(["Finding", *(NAMES[c] for c in CATEGORIES), "Points"], rows),
        f"Supported, all {spelled(len(rows))}: {total} points for categories 1 to 4. Severity and breadth "
        f"alone: {stated} self-assessed, {supported} supported. "
        + ("Every finding scores at least 1 in each of the four categories, the rubric's floor "
           "for earning any points." if floor else
           "At least one finding scores 0 in a category, so it earns no points."), ""]


def scores(entry: dict) -> list[str]:
    rows = [[NAMES[c], shown(entry["scores"][c]["self"]), str(entry["scores"][c]["supported"]),
             cell(entry["scores"][c]["reason"]),
             ", ".join(entry["scores"][c]["evidence"])] for c in CATEGORIES]
    return grid_table(["", "Self-score", "Supported", "Why, in the rubric's words", "Evidence"],
                      rows)


def claims(entry: dict) -> list[str]:
    if not entry["claims"]:
        return ["The audits weaken no claim in this finding's text.", ""]
    lines = ["Claims the audits weaken or refute:", ""]
    for number, claim in enumerate(entry["claims"], 1):
        lines += [f"{number}. **{claim['status'].capitalize()}**: `{claim['field']}`, written by "
                  f"`{claim['owner']}` ({claim['part']}).",
                  f"   - Now: \"{claim['old']}\"",
                  f"   - Replace with: \"{claim['new']}\"",
                  f"   - Why: {claim['why']} ({', '.join(claim['evidence'])})"]
    return [*lines, ""]


def source(item: dict) -> str:
    if "run" in item:
        where = " ".join(f"{k} {item[k]}" for k in ("lang", "seed") if k in item)
        return f"run `{item['run']}`, {item['hypothesis']}{' ' + where if where else ''}"
    if item.get("absent"):
        return f"`{item['file']}` (must not exist)"
    if "quote" in item:
        return f"`{item['file']}`, quoted"
    path = " › ".join(json.dumps(s, ensure_ascii=False) if isinstance(s, dict) else str(s)
                      for s in item["path"]) or "top level"
    extra = "".join(f"; {k} {json.dumps(item[k], ensure_ascii=False)}"
                    for k in ("where", "each", "pick") if k in item)
    return f"`{item['file']}` › {path}{extra}"


def value(item: dict) -> str:
    if "run" in item:
        return f"{item['counted']} of {item['answers']} counted"
    if item.get("absent"):
        return "absent"
    if "quote" in item:
        return f"\"{item['quote']}\""
    if "contains" in item:
        return f"contains \"{item['contains']}\""
    return f"`{json.dumps(item['value'], ensure_ascii=False)}`"


def evidence(rescore: dict) -> list[str]:
    rows = [[name, cell(source(item)), cell(item.get("by", "")), cell(value(item)),
             cell(item["shows"] + (f" Reading for this rescore, not a label: {item['reading']}"
                                   if "reading" in item else ""))]
            for name, item in rescore["evidence"].items()]
    return ["## Evidence", "", *rescore["evidence_note"], "",
            *grid_table(["Id", "Source", "Written by", "Value", "What it shows"], rows)]


def markdown(rescore: dict) -> str:
    lines = [f"# {rescore['title']}", "", *(p for para in rescore["about"] for p in (para, "")),
             *summary(rescore)]
    for number, entry in enumerate(rescore["findings"], 1):
        lines += [f"## {number}. {entry['title']}", "",
                  f"`{entry['file']}`. {entry['basis']}", "", *scores(entry), *claims(entry)]
    lines += evidence(rescore)
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="check only, write nothing")
    args = parser.parse_args(argv)
    rescore = json.loads((AUDIT / "rescore.json").read_text())
    found = problems(rescore)
    for line in found:
        print(line, file=sys.stderr)
    if found:
        return 1
    if not args.check:
        (AUDIT / "rescore.md").write_text(markdown(rescore))
    print(f"rescore.json: {len(rescore['evidence'])} cited values and counts hold, "
          f"{sum(len(e['claims']) for e in rescore['findings'])} rewrites fit their findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
