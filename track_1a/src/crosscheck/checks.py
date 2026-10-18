"""One checked value: where a findings file, numbers.json or the report states it, the value
stated, the value recomputed from the recorded data, and whether the two agree."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .bounds import Bound

WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
         "nine": 9, "ten": 10}


def rounding(places: int) -> float:
    """How far a value written to some decimal places may sit from the one it stands for."""
    return 0.5 * 10 ** -places


@dataclass(frozen=True)
class Check:
    source: str
    expected: object
    recomputed: object
    tolerance: float = 0
    constant: bool = False  # recomputed is a design constant used as given, not re-derived

    @property
    def ok(self) -> bool:
        return agree(self.expected, self.recomputed, self.tolerance)

    @property
    def numeric(self) -> bool:
        stated = self.expected
        return number(stated) or (isinstance(stated, list) and bool(stated)
                                  and all(map(number, stated)))

    def bounds(self) -> list[tuple[float, Bound]]:
        """Each stated number paired with the bootstrap bound recomputed for it."""
        stated, mine = self.expected, self.recomputed
        if not isinstance(mine, list):
            stated, mine = [stated], [mine]
        if not isinstance(stated, list):
            return []
        return [(s, m) for s, m in zip(stated, mine) if isinstance(m, Bound) and number(s)]

    @property
    def estimated(self) -> bool:
        """Agrees, but a stated bound is a 2000-draw estimate away from the exact quantile."""
        return self.ok and any(m.spread and abs(s - m.value) > self.tolerance + 1e-9
                               for s, m in self.bounds())

    def line(self) -> str:
        constant = " (design constant)" if self.constant else ""
        tolerance = f" (tolerance {self.tolerance:g})" if self.tolerance else ""
        return (f"{self.source}{constant} | expected {show(self.expected)} | recomputed "
                f"{show(self.recomputed)}{tolerance} | {'OK' if self.ok else 'DIFF'}{self.note()}")

    def note(self) -> str:
        if self.estimated:
            return " (a 2000-draw estimate off the exact quantile)"
        pairs = self.bounds()
        if self.ok or len(pairs) != 2:
            return ""
        (low, mine_low), (high, mine_high) = pairs
        wider = low <= mine_low.value and high >= mine_high.value
        return f" (stated interval is {'wider' if wider else 'narrower or shifted'})"

    def record(self) -> dict:
        out = {"source": self.source, "expected": self.expected,
               "recomputed": plain(self.recomputed), "tolerance": self.tolerance, "ok": self.ok}
        cdf = [m.position(s, self.tolerance) for s, m in self.bounds() if m.spread]
        if cdf:
            out["stated_cdf"] = cdf
        if self.constant:
            out["constant"] = True
        return out


def number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def agree(expected, recomputed, tolerance: float) -> bool:
    if isinstance(recomputed, Bound):
        return number(expected) and recomputed.admits(expected, tolerance)
    if isinstance(expected, (list, tuple)) and isinstance(recomputed, (list, tuple)):
        return len(expected) == len(recomputed) and all(
            agree(e, r, tolerance) for e, r in zip(expected, recomputed))
    if isinstance(expected, dict) and isinstance(recomputed, dict):
        return expected.keys() == recomputed.keys() and all(
            agree(expected[k], recomputed[k], tolerance) for k in expected)
    if tolerance and number(expected) and number(recomputed):
        return abs(expected - recomputed) <= tolerance + 1e-9
    return expected == recomputed


def plain(value):
    """The value with each bound written out as JSON can hold it."""
    if isinstance(value, Bound):
        return value.record()
    if isinstance(value, (list, tuple)):
        return [plain(x) for x in value]
    return value


def show(value) -> str:
    if isinstance(value, Bound):
        return value.text()
    if isinstance(value, (list, tuple)) and any(isinstance(x, Bound) for x in value):
        return "[" + ", ".join(map(show, value)) + "]"
    return json.dumps(value, ensure_ascii=False)


def pct(rate: float) -> int:
    """A rate as the whole percentage a text prints for it."""
    return round(100 * rate)


def rounded(values, places: int = 3) -> list[float]:
    return [round(x, places) for x in values]


def flat(text: str) -> str:
    """The text as one line, without the markers of a Markdown blockquote."""
    return " ".join(re.sub(r"(?m)^\s*> ?", "", text).split())


def value(text: str | None):
    """A number as a text writes it: digits, a signed or decimal number, or a small number word;
    any other text stays as it is."""
    if text is None:
        return None
    written = text.replace("−", "-")
    if re.fullmatch(r"[+-]?\d+", written):
        return int(written)
    if re.fullmatch(r"[+-]?\d+\.\d+", written):
        return float(written)
    return WORDS.get(written.lower(), text)


def stated(source: str, text: str, pattern: str, recomputed: dict, tolerance: float = 0,
           at_start: bool = False) -> list[Check]:
    """A check per group of the pattern, labelled by the keys of recomputed in group order. Text
    the pattern no longer finds is a difference too, so a reworded sentence is looked at again."""
    match = (re.match if at_start else re.search)(pattern, flat(text))
    if match is None:
        return [Check(f"{source} /{pattern}/", "a sentence matching the pattern", "none found")]
    return [Check(f"{source} {label}", value(found), mine, tolerance)
            for (label, mine), found in zip(recomputed.items(), match.groups(), strict=True)]


def shares(at: str, said: dict, share) -> list[Check]:
    """The rate, Wilson interval and counts a file states for one share."""
    return [Check(f"{at}.rate", said.get("rate"), round(share.rate, 3)),
            Check(f"{at}.ci95", said.get("ci95"), rounded(share.wilson)),
            Check(f"{at}.k", said.get("k"), share.k),
            Check(f"{at}.n", said.get("n"), share.n)]


def present(source: str, text: str, phrase: str, recomputed: bool, label: str = "") -> Check:
    """Whether a text says something the recomputed numbers do or do not support."""
    return Check(f"{source} says {label or repr(phrase)}", phrase in flat(text), recomputed)
