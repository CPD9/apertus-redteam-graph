"""Which of the harness's six languages a text is written in, read from marker words.

lang_markers.json lists, per language, function words and spellings common in it and rare in the
other five; each list says what it leaves out and why. Every word of a text that is a marker is one
vote for its language, and the language with most votes wins. A word list is crude, but every
decision can be traced to the words that made it, and it never asks the model whose translations it
checks. It is not independent of that model's writing, though: the lists were pruned on the prompts
Apertus 70B translated and on the answers of the 8B and 70B, so its agreement on those texts is
optimistic.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path

MARKERS = Path(__file__).with_name("lang_markers.json")
UNCERTAIN = "uncertain"
MIN_VOTES = 3  # fewer marker words than this is too little to go on
MIN_LEAD = 2  # so that one stray or quoted word cannot decide between two languages
MIN_MARGIN = 0.25  # the winner's lead over the runner-up, as a share of all votes

APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'"})
# The English and Swiss German clitics 's, 'd, 't and 'm are no words of their own: it's and I'd
# must not give the Swiss German articles s and d. A Romance elision before a one-letter word
# (jusqu'à, ch'i) keeps both words.
CLITIC = re.compile(r"(?<=[^\W\d_])'[sdtm]\b")
# The letters of an abbreviation (U.S., d. h., z.B., D.Lgs.) are no words either. After a space only
# one more letter belongs to it, so that in "the U.S. law." the word law stays.
ABBREVIATION = re.compile(r"\b[^\W\d_]\.(?:[^\W\d_]+\.|\s[^\W\d_]\.)+")
# A word keeps a following apostrophe when a letter comes next, so the elided l', qu', ch' and z'
# are words of their own.
WORD = re.compile(r"\b[^\W\d_]+(?:'(?=[^\W\d_]))?")


@dataclass(frozen=True)
class Profile:
    lang: str  # the language with most votes, or UNCERTAIN when the evidence is thin
    best: str  # the language with most votes even when uncertain; "" without any vote
    margin: float  # the winner's lead over the runner-up, as a share of all votes
    votes: dict[str, int]
    matched: list[tuple[str, str]]  # each marker word found, with its language, in text order


@cache
def markers() -> dict[str, str]:
    """Each marker word with its language. A word listed for two languages could only blur the
    vote, so the lists must not share one."""
    table = {}
    for lang, entry in json.loads(MARKERS.read_text()).items():
        for word in entry["markers"]:
            if table.setdefault(word, lang) != lang:
                raise ValueError(f"{word!r} is a marker of both {table[word]} and {lang}")
    return table


def languages() -> list[str]:
    return list(dict.fromkeys(markers().values()))


def words(text: str) -> list[str]:
    """The words of a text, case-folded, with every apostrophe written as ', and without clitics
    and the letters of abbreviations."""
    text = unicodedata.normalize("NFC", text).translate(APOSTROPHES).casefold()
    return WORD.findall(ABBREVIATION.sub(" ", CLITIC.sub("", text)))


def matches(text: str) -> list[tuple[str, str]]:
    """Each marker word of a text with its language, in text order."""
    table = markers()
    return [(word, table[word]) for word in words(text) if word in table]


def profile(text: str) -> Profile:
    matched = matches(text)
    votes = Counter(lang for _, lang in matched)
    ranked = sorted(languages(), key=lambda lang: -votes[lang])  # stable: ties keep list order
    total = sum(votes.values())
    if not total:
        return Profile(UNCERTAIN, "", 0.0, {}, [])
    best, second = ranked[0], ranked[1]
    lead = votes[best] - votes[second]
    clear = total >= MIN_VOTES and lead >= MIN_LEAD and lead / total >= MIN_MARGIN
    return Profile(best if clear else UNCERTAIN, best, round(lead / total, 4),
                   dict(votes.most_common()), matched)
