"""Are the attack prompts in the language they are meant to be in? Apertus 70B translated them and,
in the harness, also names their language (agents.language_check). Here a word list
(redteam.lang_profile) that never asks the model, but was pruned on these same prompts and answers,
reads the last prompts of every hypothesis and the answers they drew, and the counted wrong-answer
rates are recomputed without the prompts either check puts in another language. The answers of two
runs the lists were not pruned on show how far the word list can be trusted. Writes
docs/audit/stimuli.json and docs/audit/stimuli.md.

    cd track_1a && python3 scripts/report_stimuli.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # without pip install -e

from report_pooling import DRAWS, difference, pooled, resamples  # noqa: E402
from report_stimuli_note import markdown  # noqa: E402
from report_stimuli_prompts import (PAIRS, UNCERTAIN, UNLOGGED, checks, excerpt,  # noqa: E402
                                    last_prompts, listed, listing, totals)

from redteam import answers, lang_profile, paths  # noqa: E402
from redteam.cache import CACHE_DIR  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "audit"
SMALL, LARGE = "20261016-172309-1f71", "20261017-140533-a21a"
BANK2, MITIGATION = "20261017-143329-b04d", "20261017-144423-5519"
HYPOTHESES = {h["id"]: h for h in load_hypotheses()}
# Which prompts a rate keeps: all, all but those the word list puts in another language, or all
# but those the harness check names another language.
FILTERS = {"all prompts": lambda row: True,
           "word list kept": lambda row: row["words"] in (row["lang"], UNCERTAIN),
           "harness kept": lambda row: row["harness"] in (row["lang"], UNLOGGED)}


def cells(run):
    """(counted, answers) per hypothesis and language."""
    out = {}
    for answer in run.answers:
        counted, total = out.get((answer.hypothesis, answer.lang), (0, 0))
        out[(answer.hypothesis, answer.lang)] = (counted + answer.confirmed, total + 1)
    return out


def rate(table):
    return {"hypotheses": len(table), **pooled(table, resamples(len(table)))}


def rates(run, rows):
    """Counted rate per language and the Romansh minus English gap under each filter, with the
    prompts each filter leaves out. The gap filters only the Romansh prompts and sets them against
    English on the same hypotheses."""
    by_cell = {(row["hypothesis"], row["lang"]): row for row in rows}
    grid = cells(run)
    out = {}
    for name, keep in FILTERS.items():
        kept = {key: cell for key, cell in grid.items() if keep(by_cell[key])}
        tables = {lang: [kept[(h, lang)] for h in run.hypotheses if (h, lang) in kept]
                  for lang in run.langs}
        both = [h for h in run.hypotheses if (h, "rm") in kept and (h, "en") in grid]
        gap = difference([grid[(h, "en")] for h in both], [kept[(h, "rm")] for h in both],
                         resamples(len(both))) if both else {}
        out[name] = {"per_lang": {lang: rate(table) for lang, table in tables.items() if table},
                     "rm_minus_en": {"hypotheses": len(both), **gap},
                     "left_out": dict(Counter(lang for h, lang in grid if (h, lang) not in kept))}
    return out


def answer_languages(run):
    """The word list's reading of the answers to each prompt language, and their median length."""
    out = {}
    for lang in run.langs:
        texts = [answer.text for answer in run.answers if answer.lang == lang]
        if texts:
            found = Counter(lang_profile.profile(text).lang for text in texts)
            out[lang] = {"answers": len(texts), "languages": dict(found.most_common()),
                         "median_chars": median(map(len, texts)),
                         "median_words": median(len(lang_profile.words(text)) for text in texts)}
    return out


def answers_listed(runs):
    """Each answer to a Swiss German or Romansh prompt that the word list reads as the pair
    language, with the votes that decided it."""
    out = []
    for run_id, run in runs.items():
        for answer in run.answers:
            found = lang_profile.profile(answer.text) if answer.lang in PAIRS else None
            if found and found.lang == PAIRS[answer.lang]:
                out.append({"run": run_id, "hypothesis": answer.hypothesis, "lang": answer.lang,
                            "seed": answer.seed, "votes": found.votes,
                            "counted": answer.confirmed, "excerpt": excerpt(answer.text)})
    return out


def agreement(by_run):
    """How many answers the word list puts in their prompt's language, leaves uncertain, or puts
    in another language."""
    total = Counter()
    for by_lang in by_run.values():
        for lang, cell in by_lang.items():
            total.update(answers=cell["answers"], prompt_language=cell["languages"].get(lang, 0),
                         uncertain=cell["languages"].get(UNCERTAIN, 0))
    total["elsewhere"] = total["answers"] - total["prompt_language"] - total["uncertain"]
    return dict(total)


def main(out=OUT, runs_root=paths.SHIPPED, cache_root=CACHE_DIR, prompted=(SMALL, LARGE, BANK2),
         answered=(SMALL, LARGE), held_out=(BANK2, MITIGATION)):
    prompts = {run_id: last_prompts(runs_root / run_id) for run_id in prompted}
    runs = {run_id: answers.load_run(runs_root / run_id, HYPOTHESES, cache_root)
            for run_id in dict.fromkeys(answered + held_out)}
    read = {run_id: checks(rows) for run_id, rows in prompts.items()}
    entries = listed(prompts)
    unseen = {run_id: answer_languages(runs[run_id]) for run_id in held_out}
    numbers = {
        "script": "scripts/report_stimuli.py",
        "word_list": {"markers": dict(Counter(lang_profile.markers().values())),
                      "min_votes": lang_profile.MIN_VOTES, "min_lead": lang_profile.MIN_LEAD,
                      "min_margin": lang_profile.MIN_MARGIN},
        "bootstrap": {"draws": DRAWS, "seed": 1, "clusters": "hypotheses"},
        "runs": {"prompts": list(prompted), "answers": list(answered), "held_out": list(held_out)},
        "models": {run_id: run.model for run_id, run in runs.items()},
        "system_prompt": [run_id for run_id, run in runs.items() if run.system],
        "prompts": read,
        "prompts_total": totals(read),
        "listing": listing(entries),
        "listed": entries,
        "rates": {run_id: rates(runs[run_id], prompts[run_id]) for run_id in answered},
        "answers": {run_id: answer_languages(runs[run_id]) for run_id in answered},
        "answers_listed": answers_listed({run_id: runs[run_id] for run_id in answered}),
        "held_out": {"answers": unseen, "total": agreement(unseen)}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "stimuli.json").write_text(json.dumps(numbers, indent=1, ensure_ascii=False) + "\n")
    (out / "stimuli.md").write_text(markdown(numbers))
    return numbers


if __name__ == "__main__":
    main()
