"""What /review.html shows: the blind set of judge decisions, and the Swiss German and Romansh
prompts for the native speakers' check.

The judge set is 60 answers of the 8B and 70B runs, drawn with a fixed seed: as many from each
language, half counted by the judge (Answer.confirmed) and half not, and half from each run. Every
labeller gets the same items in the same order, so two of them overlap. An item's id is a hash, and
which run answered, the seed and the judge's verdict stay on the server.
"""
from __future__ import annotations

import random
from collections import Counter
from functools import lru_cache
from hashlib import sha1
from pathlib import Path

from . import answers, paths
from .cache import CACHE_DIR
from .events import read_events
from .run import load_hypotheses

RUNS = {"20261016-172309-1f71": "8B", "20261017-140533-a21a": "70B"}
PROMPT_RUNS = (*RUNS, "20261017-144423-5519", "20261017-143329-b04d")
SET_SIZE, SEED = 60, 20261019
CHECKED_LANGS = ("gsw", "rm")
HIDDEN = ("judge_counts", "judge_quote", "run_id", "seed", "detected")


@lru_cache(maxsize=1)
def bank() -> dict[str, dict]:
    return {h["id"]: h for h in load_hypotheses()}


@lru_cache(maxsize=8)
def _load(folder: Path, cache_root: Path) -> answers.Run:
    return answers.load_run(folder, bank(), cache_root)


def load(run_id: str) -> answers.Run:
    folder = paths.run_dir(run_id)
    if folder is None:
        raise ValueError(f"run {run_id} is not in runs/ or data/runs/")
    return _load(folder, CACHE_DIR)


def population(run_id: str) -> Counter:
    """The run's answers per (language, judge verdict)."""
    return Counter((a.lang, a.confirmed) for a in load(run_id).answers)


def quotas(cells: list[tuple[tuple, int]], size: int) -> dict[tuple, int]:
    """size spread over the cells, each given with its parity. The leftover goes to the even cells
    first, so on a checkerboard of (language, verdict, run) every margin gets the same share when
    the leftover is half the cells, as for 60 items over 24 cells."""
    base, extra = divmod(size, len(cells))
    ranked = sorted(cells, key=lambda cell: cell[1])
    return {key: base + (rank < extra) for rank, (key, _) in enumerate(ranked)}


def spread(pool: list, k: int, rng: random.Random) -> list:
    """k at random, each from another hypothesis for as long as there are enough of them."""
    pool, seen, ranks = rng.sample(pool, len(pool)), Counter(), []
    for a in pool:
        seen[a.hypothesis] += 1
        ranks.append(seen[a.hypothesis])
    return [a for _, a in sorted(zip(ranks, pool), key=lambda pair: pair[0])][:k]


def item(run: answers.Run, a: answers.Answer) -> dict:
    hyp = bank()[a.hypothesis]
    key = f"{run.id}:{a.hypothesis}:{a.lang}:{a.seed}"
    english = None if a.lang == "en" else run.prompts.get(a.hypothesis, {}).get("en")
    return {"id": sha1(key.encode()).hexdigest()[:12], "run_id": run.id, "seed": a.seed,
            "hypothesis": a.hypothesis, "title": hyp.get("title", a.hypothesis), "lang": a.lang,
            "question": a.prompt, "english": english, "answer": a.text,
            "reference": hyp["reference"], "judge_counts": a.confirmed, "judge_quote": a.evidence}


def blind_set(size: int = SET_SIZE, seed: int = SEED) -> list[dict]:
    rng, runs = random.Random(seed), {run_id: load(run_id) for run_id in RUNS}
    langs = list(dict.fromkeys(lang for run in runs.values() for lang in run.langs))
    cells = [((lang, counted, run_id), (i + j + k) % 2) for i, lang in enumerate(langs)
             for j, counted in enumerate((True, False)) for k, run_id in enumerate(runs)]
    chosen = []
    for (lang, counted, run_id), k in quotas(cells, size).items():
        pool = [a for a in runs[run_id].answers if (a.lang, a.confirmed) == (lang, counted)]
        chosen += [item(runs[run_id], a) for a in spread(pool, k, rng)]
    rng.shuffle(chosen)
    return chosen


def stimuli(lang: str) -> list[dict]:
    """Every gsw or rm prompt the recorded runs verified, each text once, with the attacker's
    prompt it was translated from (German in most runs; every language is its own translation of
    it) and the harness's own check of its language (the mutator's detected)."""
    if lang not in CHECKED_LANGS:
        raise ValueError(f"the language check covers gsw and rm, not {lang!r}")
    found = {}
    for folder in filter(None, map(paths.run_dir, PROMPT_RUNS)):
        source, last = {}, {}
        for e in read_events(folder / "events.jsonl"):
            step, hyp = (e["node"], e["status"]), e["hypothesis"]
            if step == ("attacker", "done"):
                source[hyp] = e["data"].get("prompt")
            elif step == ("mutator", "done"):
                last[hyp] = {**e["data"], "source": source.get(hyp)}
            elif step == ("verifier", "start") and last.get(hyp, {}).get("prompts", {}).get(lang):
                text = last[hyp]["prompts"][lang]
                found.setdefault(text, {"id": f"{lang}:{sha1(text.encode()).hexdigest()[:12]}",
                                        "lang": lang, "hypothesis": hyp, "question": text,
                                        "source": last[hyp]["source"],
                                        "detected": last[hyp].get("detected", {}).get(lang)})
    items = sorted(found.values(), key=lambda s: s["id"])
    random.Random(SEED).shuffle(items)
    return items


def public(it: dict) -> dict:
    return {k: v for k, v in it.items() if k not in HIDDEN}


def find(items: list[dict], item_id) -> dict:
    found = next((it for it in items if it["id"] == item_id), None)
    if found is None:
        raise ValueError(f"unknown item {item_id!r}")
    return found
