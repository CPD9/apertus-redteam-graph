"""Human labels from /review.html: a blind check of the judge on the set of review_set.py, and
native speakers' check of the Swiss German and Romansh prompts. Nothing here makes a label.

A label row keeps the labeller, the item's id, the label, whether the answer hedges and a note.
The judge's verdict, run and language are joined from the set when labels are read, so the file
gives nothing away. A labeller sees the verdicts only by asking, which ends their labelling, and
only from then on do their labels count against the judge. A later label by the same person for
the same item replaces the earlier one. The figures are in review_stats.py.

    PYTHONPATH=src python3 -m redteam.review
"""
from __future__ import annotations

import json
import threading
import time

from . import paths, review_set
from .agents import LANG_NAMES
from .review_stats import (between_people, grouped, hedged_as_no, judge_accuracy, judge_pairs,
                           share, tally)
from .review_stats import cohen_kappa  # noqa: F401  rejudge.py and the scripts import it here

LABELS = paths.ROOT / "data" / "labels" / "judge.jsonl"
RATINGS = paths.ROOT / "data" / "labels" / "language.jsonl"
# The page's choices and how a row stores them: human_violation, null for "can't tell".
JUDGE_LABELS = {"asserts": True, "does_not": False, "cant_tell": None}
LANGUAGE_LABELS = ("natural", "odd", "not_this_language")
NOTE_LENGTH = 500
_lock = threading.Lock()


class Closed(Exception):
    """The labeller has seen the judge's verdicts, so a later label would not be blind."""


def labeller(name) -> str:
    name = " ".join(str(name or "").split())
    if not 0 < len(name) <= 40:
        raise ValueError("a labeller name of 1 to 40 characters is needed")
    return name


def _checked(label, allowed, note) -> str:
    """The note, once the label is one of allowed and the note is text of a sane length."""
    if not isinstance(label, str) or label not in allowed:
        raise ValueError(f"the label must be one of {', '.join(allowed)}")
    note = "" if note is None else note
    if not isinstance(note, str) or len(note) > NOTE_LENGTH:
        raise ValueError(f"a note is text of at most {NOTE_LENGTH} characters")
    return note.strip()


def _rows(path) -> list[dict]:
    lines = path.read_text().splitlines() if path.exists() else []
    return [json.loads(line) for line in lines if line.strip()]


def _latest(path) -> list[dict]:
    """The label rows, the last one per labeller and item."""
    return list({(r.get("labeller"), r["id"]): r for r in _rows(path) if "id" in r}.values())


def _append(path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {**row, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def labels() -> list[dict]:
    return _latest(LABELS)


def revealed_at(name: str) -> str | None:
    return next((r["at"] for r in _rows(LABELS) if r.get("revealed") and r["labeller"] == name),
                None)


def save_label(name, item_id, label, note="", hedged=False) -> dict:
    name, note = labeller(name), _checked(label, JUDGE_LABELS, note)
    if not isinstance(hedged, bool):
        raise ValueError("hedged is true or false")
    review_set.find(review_set.blind_set(), item_id)
    with _lock:
        if revealed_at(name):
            raise Closed(f"{name} has seen the judge's verdicts; later labels would not be blind")
        _append(LABELS, {"labeller": name, "id": item_id, "human_violation": JUDGE_LABELS[label],
                         "hedged": hedged, "note": note})
    return {"saved": item_id}


def save_rating(name, item_id, label, note="") -> dict:
    name, note = labeller(name), _checked(label, LANGUAGE_LABELS, note)
    review_set.find(review_set.stimuli(str(item_id).partition(":")[0]), item_id)
    with _lock:
        _append(RATINGS, {"labeller": name, "id": item_id, "rating": label, "note": note})
    return {"saved": item_id}


def reveal(name) -> dict:
    name = labeller(name)
    with _lock:
        if not revealed_at(name):
            _append(LABELS, {"labeller": name, "revealed": True})
    return verdicts(name)


def judged(rows: list[dict]) -> list[dict]:
    """The rows of the set's items, each with its item's judge verdict, quote, run, language and
    hypothesis."""
    items = {it["id"]: it for it in review_set.blind_set()} if rows else {}
    return [{**r, "judge_violation": items[r["id"]]["judge_counts"],
             **{k: items[r["id"]][k] for k in ("judge_quote", "run_id", "lang", "hypothesis")}}
            for r in rows if r["id"] in items]


def verdicts(name: str) -> dict:
    """One labeller's labels beside the judge's verdicts and quotes, for the reveal."""
    mine = judged([r for r in labels() if r.get("labeller") == name])
    return {"agreement": tally(judge_pairs(mine)), "items": [
        {k: r[k] for k in ("id", "human_violation", "hedged", "judge_violation", "judge_quote")}
        for r in mine]}


def _session(name: str, items: list[dict], rows: list[dict], label_of) -> dict:
    done = {r["id"]: {"label": label_of(r), "note": r["note"], "hedged": r.get("hedged", False)}
            for r in rows if r.get("labeller") == name}
    return {"labeller": name, "items": [review_set.public(it) for it in items], "done": done}


def session(name) -> dict:
    """The set without the judge's verdicts, the labeller's labels so far and the reveal, once
    they have asked for it."""
    name, choice = labeller(name), {stored: label for label, stored in JUDGE_LABELS.items()}
    return {**_session(name, review_set.blind_set(), labels(),
                       lambda r: choice[r["human_violation"]]),
            "reveal": verdicts(name) if revealed_at(name) else None}


def stimuli_session(lang, name) -> dict:
    items = review_set.stimuli(lang)
    return _session(labeller(name), items, _latest(RATINGS), lambda r: r["rating"])


def agreement() -> dict:
    """How many judge verdicts people have checked, for the dashboard, and how many they agree
    with. A row that carries the judge's verdict itself keeps it."""
    rows = labels()
    carried = [r for r in rows if "judge_violation" in r]
    return share(judge_pairs(carried + judged([r for r in rows if "judge_violation" not in r])))


def labellers(rows: list[dict]) -> list[dict]:
    """Who labelled how much, and when they saw the verdicts: a label after that was not blind."""
    return [{"name": name, "labels": sum(r["labeller"] == name for r in rows),
             "cant_tell": sum(r["labeller"] == name and r["human_violation"] is None for r in rows),
             "hedged": sum(r["labeller"] == name and r["hedged"] for r in rows),
             "last_label_at": max(r["at"] for r in rows if r["labeller"] == name),
             "revealed_at": revealed_at(name)} for name in sorted({r["labeller"] for r in rows})]


def report() -> dict:
    """Everything the labels say. Against the judge, only the labels of people who have seen its
    verdicts count: anything else would show them the verdicts before they finish."""
    rows = judged(labels())
    who = labellers(rows)
    seen = {w["name"] for w in who if w["revealed_at"]}
    done = [r for r in rows if r["labeller"] in seen]
    out = {"set": {"size": review_set.SET_SIZE, "seed": review_set.SEED, "runs": review_set.RUNS},
           "labels": len(rows), "labellers": who, "language_check": language_report()}
    pairs = judge_pairs(done)
    if not pairs:
        return {**out, "judge_human": None}
    return {**out, "judge_human": {
        "all": tally(pairs), "hedged_as_no": tally(judge_pairs(hedged_as_no(done))),
        "per_lang": grouped(done, "lang"), "per_labeller": grouped(done, "labeller")},
        "between_people": between_people([r for r in done if r["human_violation"] is not None],
                                         "human_violation"),
        "judge_accuracy": {name: judge_accuracy([r for r in done if r["run_id"] == run_id],
                                                review_set.population(run_id))
                           for run_id, name in review_set.RUNS.items()}}


def language_report() -> dict:
    """Per language: how often each rating was given, how often the harness's own check named the
    language for it, and how far two speakers agree on the prompts both rated."""
    rows, out = _latest(RATINGS), {}
    for lang in review_set.CHECKED_LANGS if rows else ():
        found = {s["id"]: s for s in review_set.stimuli(lang)}
        mine = [{**r, **found[r["id"]]} for r in rows if r["id"] in found]
        named = {k: [r["detected"] == LANG_NAMES[lang] for r in mine if r["rating"] == k]
                 for k in LANGUAGE_LABELS}
        if mine:
            out[lang] = {"ratings": {k: {"n": len(v), "harness_names_it": sum(v)}
                                     for k, v in named.items()},
                         "between_people": between_people(mine, "rating", with_kappa=False)}
    return out


def main() -> None:
    r = report()
    print(json.dumps(r, indent=1, ensure_ascii=False) if r["labels"] or r["language_check"] else
          f"No human labels yet. Label the {review_set.SET_SIZE} answers on /review.html "
          "(make dashboard); this report then fills in by itself.")


if __name__ == "__main__":
    main()
