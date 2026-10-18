"""Markdown for the notes in docs/audit, which each script writes from the JSON it has just written:
tables, numbers rounded as a reader rounds them, and a check that a sentence written into a note
still fits the numbers beside it.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MINUS = "−"


def grid_table(header, rows) -> list[str]:
    return [f"| {' | '.join(header)} |", "|" + "---|" * len(header),
            *(f"| {' | '.join(map(str, r))} |" for r in rows), ""]


def section(title, notes, header, rows) -> list[str]:
    return [f"## {title}", "", *(line for note in notes for line in (note, "")),
            *grid_table(header, rows)]


def split(t, first="higher", second="lower") -> str:
    holm = f" (Holm {t['p_holm']})" if "p_holm" in t else ""
    return f"{t[first]}/{t[second]}, p {t['p']}{holm}"


def with_holm(t) -> str:
    return f"{t['p']} (Holm {t['p_holm']})"


def rounded(x, places: int = 2, stored: int | None = None) -> str:
    """x to places decimals, half up, with a true minus sign. stored is how many decimals the JSON
    keeps. When that is one more than shown and the last one is a 5, x is shown as stored: 0.675
    can stand for 0.6747, so rounding it a second time could go the wrong way."""
    value = Decimal(str(x)).normalize()
    _, digits, exponent = value.as_tuple()
    if stored != places + 1 or exponent != -stored or digits[-1] != 5:
        value = value.quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    return str(value + 0).replace("-", MINUS)  # + 0 turns -0.00 into 0.00


def percent(x, places: int = 0, stored: int | None = None) -> str:
    return rounded(Decimal(str(x)) * 100, places, None if stored is None else stored - 2)


def two(x, stored: int = 3) -> str:
    """Two decimals of a value the JSON keeps to stored decimals, or – for none."""
    return "–" if x is None else rounded(x, 2, stored)


def span(t, stored: int = 3) -> str:
    return "–" if t is None else f"{two(t[0], stored)}–{two(t[1], stored)}"


def spelled(n: int) -> str:
    return "no one two three four five six seven eight nine ten".split()[n] if n <= 10 else str(n)


def signed(text: str) -> str:
    """A rounded number with its sign, so that a difference reads as one."""
    return text if text.startswith(MINUS) or text.strip("0.") == "" else "+" + text


def ratio(t: dict) -> str:
    """k/n of a share in the JSON, or – when it has no answers."""
    return f"{t['k']}/{t['n']}" if t["n"] else "–"


def listed(items) -> str:
    """Items as a sentence lists them: "a", "a and b", "a, b and c"."""
    items = [str(i) for i in items]
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def spread(values, word: str) -> str:
    """The smallest and the largest of values, "7 or 8", or one number when they are equal."""
    low, high = min(values), max(values)
    return str(low) if low == high else f"{low} {word} {high}"


def holds(condition: bool, sentence: str) -> None:
    """Stops a note whose fixed wording no longer fits its numbers. The JSON is written by then;
    the sentence needs rewriting before the note can be."""
    if not condition:
        raise SystemExit(f"the note's wording no longer fits its numbers, rewrite: {sentence}")
