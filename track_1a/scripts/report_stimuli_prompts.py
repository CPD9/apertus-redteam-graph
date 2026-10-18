"""The attack prompts of a run read by two checks: the harness's, which asks Apertus 70B to name
their language (logged as "detected" with each translation), and the word list of
redteam.lang_profile. Also the prompts a native speaker should read first.
"""
from __future__ import annotations

import re
from collections import Counter

from redteam import lang_profile
from redteam.agents import LANG_NAMES
from redteam.events import read_events

CODES = {name: code for code, name in LANG_NAMES.items()}  # the names the harness check logs
UNCERTAIN, UNLOGGED = lang_profile.UNCERTAIN, "unlogged"
PAIRS = {"gsw": "de", "rm": "it"}  # the language each is most easily mistaken for
MIXED = 1 / 3  # the pair language's share of the pair's votes from which a prompt counts as mixed
MIXED_VOTES = 2  # and the fewest votes it needs, so that one stray word does not list a prompt
EXCERPT = 120


def last_prompts(run_dir):
    """The prompts each hypothesis ended with, per language, read by the harness check (as logged)
    and by the word list."""
    last = {}
    for event in read_events(run_dir / "events.jsonl"):
        if (event["node"], event["status"]) == ("mutator", "done"):
            last[event["hypothesis"]] = event["data"]
    rows = []
    for hyp, data in last.items():
        for lang, text in data["prompts"].items():
            named = data.get("detected", {}).get(lang)
            found = lang_profile.profile(text)
            rows.append({"hypothesis": hyp, "lang": lang, "text": text, "words": found.lang,
                         "votes": found.votes,
                         "harness": UNLOGGED if named is None else CODES.get(named, "other")})
    return rows


def confusion(rows, key):
    out = {}
    for row in rows:
        out.setdefault(row["lang"], Counter())[row[key]] += 1
    return {lang: dict(found.most_common()) for lang, found in out.items()}


def flags(rows):
    """Per language, the prompts each check puts in another language, those both do, and those the
    word list cannot place or the harness did not check."""
    out = {}
    for row in rows:
        harness = row["harness"] not in (row["lang"], UNLOGGED)
        words = row["words"] not in (row["lang"], UNCERTAIN)
        out.setdefault(row["lang"], Counter()).update(
            prompts=1, harness=harness, word_list=words, both=harness and words,
            uncertain=row["words"] == UNCERTAIN, unlogged=row["harness"] == UNLOGGED)
    return {lang: dict(cell) for lang, cell in out.items()}


def checks(rows):
    return {"word_list": confusion(rows, "words"), "harness": confusion(rows, "harness"),
            "flags": flags(rows)}


def totals(by_run):
    """The flags of every run and language added up, and the English prompts the harness check
    calls German."""
    total = Counter()
    for run in by_run.values():
        for cell in run["flags"].values():
            total.update(cell)
    total["english_called_german"] = sum(run["harness"].get("en", {}).get("de", 0)
                                         for run in by_run.values())
    return dict(total)


def pair_share(row):
    """The pair language's share of the votes of a gsw or rm text and its pair language."""
    mine, theirs = row["votes"].get(row["lang"], 0), row["votes"].get(PAIRS[row["lang"]], 0)
    return theirs / (mine + theirs) if mine + theirs else 0.0


def outvoted(row):
    """Another language has more marker words in the text than the intended one."""
    return max(row["votes"].values(), default=0) > row["votes"].get(row["lang"], 0)


def mixed(row):
    if row["lang"] not in PAIRS:
        return False
    return row["votes"].get(PAIRS[row["lang"]], 0) >= MIXED_VOTES and pair_share(row) >= MIXED


def excerpt(text):
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= EXCERPT else text[:EXCERPT - 1] + "…"


def listed(prompts):
    """Each distinct prompt in which another language outvotes the intended one, and each Swiss
    German or Romansh prompt mixed with its pair language, with the runs that sent it."""
    out = {}
    for run_id, rows in prompts.items():
        for row in rows:
            if not (outvoted(row) or mixed(row)):
                continue
            entry = out.setdefault((row["lang"], row["text"]), {
                "hypothesis": row["hypothesis"], "lang": row["lang"], "words": row["words"],
                "votes": row["votes"], "harness": row["harness"],
                "pair_share": round(pair_share(row), 3) if row["lang"] in PAIRS else None,
                "runs": [], "excerpt": excerpt(row["text"])})
            entry["runs"].append(run_id)
    return list(out.values())


def listing(entries):
    """The rule that lists a prompt, and how many Swiss German and Romansh prompts the word list
    reads as their pair language."""
    return {"pairs": PAIRS, "pair_share_min": round(MIXED, 4), "pair_votes_min": MIXED_VOTES,
            "read_as_pair": {lang: sum(entry["lang"] == lang and entry["words"] == pair
                                       for entry in entries) for lang, pair in PAIRS.items()}}
