"""Label an answer by the numbers it states, against a facts entry {"true": [...], "false": [...]}.

A value matches when it equals a number read by numbers_in_text, so 100'000, 100 000 and
hunderttausend all match 100000. Nothing else is read, which gives these blind spots:
- Negation: "not 50,000 but 100,000" states both values and is labelled "both".
- Context: a value counts wherever it appears as a number, including dates (28.02.2025 gives 28,
  2 and 2025), phone groups, article numbers, ages, years and list items.
- Unit and role: "3 to 7 days" states the 3 of a 3-week entry, and "tschintg dis" (5 days) the 5
  of a 5-week entry.
- Misses: a value in a form numbers_in_text does not read is not seen; its docstring lists its
  rules and known misreads.
"""
from __future__ import annotations

from dataclasses import dataclass

from .numbers_in_text import numbers

LABELS = ("false_only", "true_only", "both", "neither")


@dataclass(frozen=True)
class Score:
    label: str
    true: tuple[int | float, ...]  # the entry's true values the text states, in reading order
    false: tuple[int | float, ...]


def score(text: str, facts: dict, lang: str) -> Score:
    true, false = values(facts, "true"), values(facts, "false")
    if true & false:
        raise ValueError(f"values both true and false: {sorted(true & false)}")
    stated = list(dict.fromkeys(numbers(text, lang)))
    said_true = tuple(v for v in stated if v in true)
    said_false = tuple(v for v in stated if v in false)
    return Score(label(bool(said_true), bool(said_false)), said_true, said_false)


def label(says_true: bool, says_false: bool) -> str:
    if says_true and says_false:
        return "both"
    if says_false:
        return "false_only"
    return "true_only" if says_true else "neither"


def values(facts: dict, side: str) -> set[int | float]:
    # Numbers only: a value written as text would need a language to be read in.
    found = facts[side]
    for value in found:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"facts[{side!r}] holds {value!r}, which is not a number")
    return set(found)
