"""What docs/audit/rescore.json must still match before its note is written: each value it cites
is what its source holds now, each answer count is what the replayed run counts, each claim it
rewrites is still in its finding (or already rewritten) and fits the schema's limit after the
rewrite, and each score is argued in the rubric's own words.
"""
from __future__ import annotations

import json
from pathlib import Path

from redteam import answers, paths
from redteam.cache import CACHE_DIR
from redteam.run import load_hypotheses

TRACK = Path(__file__).resolve().parents[1]
CATEGORIES = ("severity", "breadth", "novelty", "validity")
SELF_SCORED = {"severity": "self_assessed_severity", "breadth": "self_assessed_breadth"}


def resolve(doc, path: list):
    """The value at path. A step is a key or an index; a dict step picks the one list item whose
    fields equal it, so a path does not depend on where an audit happens to list an item."""
    for step in path:
        if isinstance(step, dict):
            found = [item for item in doc
                     if isinstance(item, dict) and all(item.get(k) == v for k, v in step.items())]
            if len(found) != 1:
                raise LookupError(f"{step} matches {len(found)} items")
            doc = found[0]
        else:
            doc = doc[step]
    return doc


def narrowed(value, item: dict):
    """The part of a value the rescore cites: the list items matching 'where', the keys named in
    'pick', or the 'each' path inside every child of a dict."""
    if "where" in item:
        value = [v for v in value if all(v.get(k) == w for k, w in item["where"].items())]
    if "each" in item:
        value = {k: resolve(v, item["each"]) for k, v in value.items()}
    if "pick" in item:
        def pick(v):
            return {k: v[k] for k in item["pick"]}
        value = [pick(v) for v in value] if isinstance(value, list) else pick(value)
    return value


def squeezed(text: str) -> str:
    return " ".join(text.split())


class Replayed:
    """Counted answers of recorded runs, replayed from the LLM cache as the findings count them."""

    def __init__(self, runs_root: Path = paths.SHIPPED, cache_root: Path = CACHE_DIR):
        self.runs_root, self.cache_root, self.runs = runs_root, cache_root, {}
        self.refs = {h["id"]: h for h in load_hypotheses()}

    def count(self, item: dict) -> dict:
        if item["run"] not in self.runs:
            self.runs[item["run"]] = answers.load_run(self.runs_root / item["run"], self.refs,
                                                      self.cache_root)
        chosen = [a for a in self.runs[item["run"]].answers
                  if a.hypothesis == item["hypothesis"]
                  and item.get("lang", a.lang) == a.lang and item.get("seed", a.seed) == a.seed]
        return {"counted": sum(a.confirmed for a in chosen), "answers": len(chosen)}


def evidence_problem(name: str, item: dict, root: Path, replayed) -> str | None:
    if "run" in item:
        got = replayed.count(item)
        want = {"counted": item["counted"], "answers": item["answers"]}
        return None if got == want else f"{name}: the run counts {got}, not {want}"
    path = root / item["file"]
    if item.get("absent"):
        return f"{name}: {item['file']} exists" if path.exists() else None
    if not path.is_file():
        return f"{name}: {item['file']} is missing"
    if "quote" in item:
        found = squeezed(item["quote"]) in squeezed(path.read_text())
        return None if found else f"{name}: the quote is no longer in {item['file']}"
    doc = json.loads(path.read_text())
    if "by" in item and isinstance(doc, dict) and doc.get("script", item["by"]) != item["by"]:
        return f"{name}: {item['file']} is written by {doc['script']}, not {item['by']}"
    try:
        value = narrowed(resolve(doc, item["path"]), item)
    except (KeyError, IndexError, LookupError, TypeError) as error:
        return f"{name}: {item['file']} has no {item['path']} ({error})"
    if "contains" in item:
        return None if item["contains"] in value else f"{name}: {item['contains']!r} not found"
    return None if value == item["value"] else f"{name}: {item['file']} holds {value!r}"


def field(finding: dict, dotted: str):
    for key in dotted.split("."):
        finding = finding[key]
    return finding


def limit(schema: dict, dotted: str) -> int | None:
    *parents, last = dotted.split(".")
    props = schema["properties"]
    for key in parents:
        props = props[key]["properties"]
    return props[last].get("maxLength")


def claim_problems(entry: dict, finding: dict, schema: dict) -> list[str]:
    """Every rewrite of one finding, applied together field by field: each old wording must be
    there once, unless the new one already is, and the field must still fit."""
    problems, texts = [], {}
    for claim in entry["claims"]:
        where = f"{entry['file']} {claim['field']}"
        text = texts.setdefault(claim["field"], field(finding, claim["field"]))
        if text.count(claim["old"]) == 1:
            texts[claim["field"]] = text.replace(claim["old"], claim["new"])
        elif claim["new"] not in text:
            problems.append(f"{where}: {claim['old'][:60]!r} is not there once")
    for dotted, text in texts.items():
        most = limit(schema, dotted)
        if most is not None and len(text) > most:
            problems.append(f"{entry['file']} {dotted}: {len(text)} characters after the "
                            f"rewrites, over the schema's {most}")
    return problems


def score_problems(entry: dict, finding: dict, rubric: dict) -> list[str]:
    problems = []
    for category in CATEGORIES:
        score, where = entry["scores"][category], f"{entry['file']} {category}"
        level = rubric[category]["levels"].get(str(score["supported"]))
        if level is None:
            problems.append(f"{where}: {score['supported']} is not a rubric level")
        elif score["words"] not in level or score["words"] not in score["reason"]:
            problems.append(f"{where}: the reason does not use the words of level "
                            f"{score['supported']}")
        key = SELF_SCORED.get(category)
        now = int(finding["issue_summary"][key]) if key else None
        if now not in (score["self"], score["supported"]):
            problems.append(f"{where}: the finding self-assesses {now}, not {score['self']}")
    return problems


def problems(rescore: dict, root: Path = TRACK, replayed=None) -> list[str]:
    """Everything in the rescore that no longer matches its sources, as one line each."""
    replayed = replayed or Replayed()
    readme = (root / rescore["rubric_source"]).read_text()
    found = [f"{category} {level}: not the rubric's wording"
             for category, spec in rescore["rubric"].items()
             for level, text in spec["levels"].items() if f"**{level}:** {text}" not in readme]
    evidence = rescore["evidence"]
    found += [p for name, item in evidence.items()
              if (p := evidence_problem(name, item, root, replayed))]
    schema = json.loads((root / "findings" / "findings.schema").read_text(), strict=False)
    cited = set()
    for entry in rescore["findings"]:
        finding = json.loads((root / entry["file"]).read_text())
        found += score_problems(entry, finding, rescore["rubric"])
        found += claim_problems(entry, finding, schema)
        for part in [*entry["scores"].values(), *entry["claims"]]:
            cited.update(part["evidence"])
    found += [f"{name}: cited but not listed" for name in sorted(cited - evidence.keys())]
    found += [f"{name}: listed but never cited" for name in sorted(evidence.keys() - cited)]
    return found
