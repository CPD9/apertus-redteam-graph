"""The judge's counting rule beside a check that reads only the numbers in an answer.

Every replayed answer whose hypothesis has numeric facts (src/redteam/numeric_facts.json) gets a
label from redteam.scorer: false_only, true_only, both or neither, by which of the hypothesis's
wrong and right values it states. No LLM takes part in the label, but negation is not read either:
an answer that rejects a wrong number by repeating it states that number. The judge counts an
answer as the findings do (Answer.confirmed). Answers read by hand, with their reading, are in
docs/audit/scorer_reading.json. Writes docs/audit/scorer.json and, from it, docs/audit/scorer.md.

    cd track_1a && python3 scripts/report_scorer.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # without pip install -e

from report_pooling import DRAWS  # noqa: E402
from report_scorer_note import markdown  # noqa: E402
from report_scorer_stats import (agreement, by_label, contrast, counted, gap,  # noqa: E402
                                 says_false)

from redteam import answers, paths  # noqa: E402
from redteam.cache import CACHE_DIR  # noqa: E402
from redteam.numbers_in_text import LANGS, numbers  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402
from redteam.scorer import Score, score  # noqa: E402

TRACK = Path(__file__).resolve().parents[1]
OUT, FACTS = TRACK / "docs" / "audit", TRACK / "src" / "redteam" / "numeric_facts.json"
RUNS = {"20261016-172309-1f71": "8B", "20261017-140533-a21a": "70B",
        "20261017-144423-5519": "70B with system prompt", "20261017-143329-b04d": "70B, bank 2"}
# Every English and Romansh answer of the two runs behind the report's language gap was read.
READ_RUNS, READ_LANGS = ("20261016-172309-1f71", "20261017-140533-a21a"), ("en", "rm")
EXAMPLES, WIDTH = 10, 160


class Scored(NamedTuple):
    run: str
    answer: answers.Answer
    score: Score


def facts_table(path: Path = FACTS) -> dict[str, dict]:
    """The scorable entries as bare values, since the scorer compares values and drops units, and
    the languages an entry leaves out."""
    entries = json.loads(path.read_text())
    return {h: {"true": [f["value"] for f in e["true"]], "false": [f["value"] for f in e["false"]],
                "skip_langs": sorted(e.get("skip_langs", {}))}
            for h, e in entries.items() if "skip" not in e}


def scorable(answer, facts: dict) -> bool:
    entry = facts.get(answer.hypothesis)
    return entry is not None and answer.lang not in entry.get("skip_langs", ())


def scored(run_id: str, answer_list, facts: dict) -> list[Scored]:
    return [Scored(run_id, a, score(a.text, facts[a.hypothesis], a.lang))
            for a in answer_list if scorable(a, facts)]


def excerpt(text: str, values, lang: str, width: int = WIDTH) -> str:
    """At most width characters around the first word by which the text states one of values."""
    words, values = text.split(), set(values)
    hit = next((k for k in range(len(words))
                if values & set(numbers(" ".join(words[:k + 1]), lang))), 0)
    start, end = hit, hit + 1
    while start > 0 and len(" ".join(words[start - 1:end])) < width // 3:
        start -= 1
    while end < len(words) and len(" ".join(words[start:end + 1])) <= width - 2:
        end += 1
    body = " ".join(words[start:end])[:width - 2]
    return ("…" if start else "") + body + ("…" if end < len(words) else "")


def key(item: Scored) -> tuple:
    return item.run, item.answer.hypothesis, item.answer.lang, item.answer.seed


def looked_up(reading: dict, item: Scored, field: str) -> str:
    return reading.get(key(item), {}).get(field, "unread")


def case(item: Scored, reading: dict) -> dict:
    a, s = item.answer, item.score
    return {"run": item.run, "hypothesis": a.hypothesis, "lang": a.lang, "seed": a.seed,
            "true": list(s.true), "false": list(s.false), "flagged": a.flagged,
            "severity": a.severity, "cause": looked_up(reading, item, "cause"),
            "excerpt": excerpt(a.text, [*s.true, *s.false], a.lang)}


def sample(found: list, k: int) -> list:
    """The first k in an order set by hashing each answer's key: a random choice that keeps its
    answers when the class gains or loses others."""
    return sorted(found, key=lambda i: sha256(repr(key(i)).encode()).hexdigest())[:k]


CLASSES = {"judge_counts_scorer_true_only": lambda i: counted(i) and i.score.label == "true_only",
           "scorer_false_only_judge_not": lambda i: says_false(i) and not counted(i)}


def disagreements(items, reading: dict) -> dict:
    out = {}
    for name, test in CLASSES.items():
        found = [i for i in items if test(i)]
        causes = [looked_up(reading, i, "cause") for i in found]
        groups = Counter((i.run, i.answer.hypothesis, c) for i, c in zip(found, causes))
        langs = Counter((i.run, i.answer.lang, c) for i, c in zip(found, causes))
        out[name] = {"n": len(found), "per_run": {r: sum(i.run == r for i in found) for r in RUNS},
                     "causes": Counter(causes).most_common(),
                     "per_hypothesis": [[*k, n] for k, n in sorted(groups.items())],
                     "per_lang": [[*k, n] for k, n in sorted(langs.items())],
                     "examples": [case(i, reading) for i in sample(found, EXAMPLES)]}
    return out


def read_gap(items, reading: dict) -> dict:
    """Every English and Romansh answer of READ_RUNS by its reading and scorer label, and Romansh
    minus English counting the answers read as asserting a wrong value."""
    out = {}
    for run_id in READ_RUNS:
        chosen = [i for i in items if i.run == run_id and i.answer.lang in READ_LANGS]
        tally = Counter((i.answer.lang, i.score.label, looked_up(reading, i, "reading"))
                        for i in chosen)
        out[run_id] = {"tally": [[*k, n] for k, n in sorted(tally.items())],
                       "rm_minus_en": contrast(
                           chosen, lambda i: looked_up(reading, i, "reading") == "asserts")}
    return out


def load(run_id: str, hypotheses: dict):
    """A recorded run's replayed answers and its neutral control's, None without a control.json.
    The copy shipped in data/runs/ is read, as a fresh checkout has it."""
    found = paths.SHIPPED / run_id
    if not (found / "events.jsonl").is_file():
        raise SystemExit(f"run {run_id} not found in {paths.SHIPPED}")
    run, control = answers.load_run(found, hypotheses, CACHE_DIR), found / "control.json"
    if not control.is_file():
        return run, None
    rows = json.loads(control.read_text())
    return run, answers.neutral_answers(rows, hypotheses, run, CACHE_DIR)


def run_numbers(run, neutral, facts: dict) -> tuple[dict, list[Scored]]:
    items = scored(run.id, run.answers, facts)
    out = {"label": RUNS[run.id], "model": run.model, "system_prompt": bool(run.system),
           "judge": run.judge, "hypotheses": len(run.hypotheses), "answers": len(run.answers),
           "scorable_hypotheses": sorted({i.answer.hypothesis for i in items}),
           "left_out": sorted({f"{a.hypothesis} {a.lang}" for a in run.answers
                               if a.hypothesis in facts and not scorable(a, facts)}),
           "scored": len(items), "agreement": agreement(items),
           "language_gap": {"scorer_false_only": gap(items, says_false),
                            "judge_counts": gap(items, counted)}}
    if neutral is not None:  # the neutral questions name no wrong value
        control = scored(run.id, neutral, facts)
        out["control"] = {"answers": len(neutral), "scored": len(control),
                          "hypotheses": len({i.answer.hypothesis for i in control}),
                          "by_label": by_label(control)}
    return out, items


def load_reading(path: Path = OUT / "scorer_reading.json") -> dict:
    rows = json.loads(path.read_text())["rows"] if path.is_file() else []
    return {(r["run"], r["hypothesis"], r["lang"], r["seed"]): r for r in rows}


def numbers_of_runs(facts: dict, reading: dict) -> dict:
    hypotheses = {h["id"]: h for h in load_hypotheses()}
    out = {"script": "scripts/report_scorer.py", "facts": "src/redteam/numeric_facts.json",
           "reading": {"file": "docs/audit/scorer_reading.json", "rows": len(reading)},
           "bank_hypotheses": len(hypotheses), "scorable_hypotheses": len(facts),
           "bootstrap": {"script": "scripts/report_pooling.py", "draws": DRAWS,
                         "resampled": "hypotheses", "seed": "fixed in resamples()"},
           "examples": f"up to {EXAMPLES} per disagreement class, first by sha256 of (run, "
                       "hypothesis, lang, seed)", "runs": {}}
    every = []
    for run_id in RUNS:
        out["runs"][run_id], items = run_numbers(*load(run_id, hypotheses), facts)
        every += items
    by_lang = {lang: agreement([i for i in every if i.answer.lang == lang]) for lang in LANGS}
    out["pooled"] = {"all": agreement(every), "per_lang": by_lang}
    out["disagreements"] = disagreements(every, reading)
    out["read_en_rm"] = read_gap(every, reading)
    return out


def main():
    text = json.dumps(numbers_of_runs(facts_table(), load_reading()), indent=1, ensure_ascii=False)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "scorer.json").write_text(text + "\n")
    (OUT / "scorer.md").write_text(markdown(json.loads(text), WIDTH))


if __name__ == "__main__":
    main()
