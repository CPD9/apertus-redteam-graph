"""Every number in a text written in en, de, gsw, fr, it or rm, as values in reading order.

The rules, one line each:
- An apostrophe or a space of any width before three digits groups thousands: 100'000, 100 000.
- A dot before three digits groups thousands, except in English, where it is a decimal point.
- A comma before three digits groups thousands in English and is a decimal comma elsewhere.
- A dot or comma that comes twice before groups of three digits groups thousands everywhere.
- Thousands are grouped after one to three digits that do not start with a zero.
- Any other dot or comma is a decimal point; a second one makes a date: 1.1.2024 is 1, 1, 2024.
- Outside English a day and month closed by a dot are a date: "bis 30.11." is 30 and 11.
- After "+" or a leading zero each space-separated group stands alone, as in phone numbers.
- A word for thousand right after digits multiplies them: "100 mila" and "100mila" are 100000.
- Signs, units and currencies are dropped: "CHF -300.–" is 300, "1961–1969" is 1961 and 1969.
- Spelled-out numbers come from WORDS; Swiss German reads the German words as well as its own.
- Number words joined by a space or hyphen form a compound, which states nothing unless it is
  in WORDS: "two hundred thousand", "thirty-one", "trente et un" and "2 hundred" state nothing.
- One is never read from words: one, ein, un and uno are also articles or pronouns.
- it "sei", fr "neuf" and rm "nov" count only before a unit of time: "sei mesi", not "tu sei".
- Per cent, per mille and their translations are units, not the numbers 100 and 1000.
- The language is the question's: an answer that switches language keeps the question's rules
  for dots and commas and loses the spelled-out numbers of the language it is written in.

Known misreads: "a few thousand" is 1000; German "außer Acht" is 8; "117 118 144" is one number;
outside English "CHF 3.10." at the end of a sentence is the date 3, 10.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import NamedTuple

LANGS = ("en", "de", "gsw", "fr", "it", "rm")
SPACES = " \u00a0\u2007\u2009\u202f"
APOSTROPHES = "'’"
THOUSAND = "thousand|tausend|tuusig|tausig|mille|mila|milli"
TOKEN = re.compile(rf"(\+?)([0-9]+(?:[.,{APOSTROPHES}{SPACES}][0-9]+)*)"
                   rf"(?:[{SPACES}]?({THOUSAND})(?!\w)|(\.))?", re.IGNORECASE)
SEPARATOR = re.compile(r"([^0-9])")
DAY_MONTH = re.compile(r"(?:0?[1-9]|[12][0-9]|3[01])\.(?:0?[1-9]|1[0-2])")
JOIN = re.compile(rf"[{SPACES}\t]+|[-\u2010\u2011]")  # the hyphens: ASCII, Unicode, no-break
AND = re.compile(rf"[{SPACES}]+and[{SPACES}]+")  # "one hundred and fifty thousand"
UNITS = ("per cent", "pour cent", "per cento", "per tschient",
         "per mille", "pour mille", "pro mille", "per milli")

# Alternative spellings are split by "|"; a space or hyphen in a spelling matches either.
WORDS = [  # value, en, de, gsw (on top of de), fr, it, rm
    (2, "two", "zwei", "zwöi|zwee|zwo|zwoi", "deux", "due", "dus|duas"),
    (3, "three", "drei", "drü", "trois", "tre", "trais"),
    (4, "four", "vier", "", "quatre", "quattro", "quatter"),
    (5, "five", "fünf", "füf|föif|fümf", "cinq", "cinque", "tschintg"),
    (6, "six", "sechs", "sächs", "six", "sei", "sis"),
    (7, "seven", "sieben", "sibe|siebe", "sept", "sette", "set"),
    (8, "eight", "acht", "", "huit", "otto", "otg"),
    (9, "nine", "neun", "nüün|nün", "neuf", "nove", "nov"),
    (10, "ten", "zehn", "zäh|zää", "dix", "dieci", "diesch"),
    (11, "eleven", "elf", "ölf", "onze", "undici", "indesch"),
    (12, "twelve", "zwölf", "zwöif", "douze", "dodici", "dudesch"),
    (13, "thirteen", "dreizehn", "drizäh|dreizäh", "treize", "tredici", "tredesch"),
    (14, "fourteen", "vierzehn", "vierzäh", "quatorze", "quattordici", "quattordesch"),
    (15, "fifteen", "fünfzehn", "füfzäh|füffzäh", "quinze", "quindici", "quindesch"),
    (16, "sixteen", "sechzehn", "sächzäh|sechzäh", "seize", "sedici", "sedesch"),
    (17, "seventeen", "siebzehn", "sibezäh|sibzäh", "dix-sept", "diciassette", "deschset"),
    (18, "eighteen", "achtzehn", "achtzäh|achtzää", "dix-huit", "diciotto", "deschdotg"),
    (19, "nineteen", "neunzehn", "nüünzäh|nünzäh", "dix-neuf", "diciannove", "deschnov"),
    (20, "twenty", "zwanzig", "zwänzg|zwanzg", "vingt|vingts", "venti", "ventg"),
    (30, "thirty", "dreissig|dreißig", "drissg|drissig", "trente", "trenta", "trenta"),
    (40, "forty", "vierzig", "vierzg", "quarante", "quaranta", "quaranta"),
    (50, "fifty", "fünfzig", "füfzg|fufzg", "cinquante", "cinquanta", "tschuncanta"),
    (60, "sixty", "sechzig", "sächzg|sechzg", "soixante", "sessanta", "sessanta"),
    (64, "sixty-four", "vierundsechzig", "vierasächzg|vieresächzg", "soixante-quatre",
     "sessantaquattro", "sessantaquatter"),
    (65, "sixty-five", "fünfundsechzig", "füfasächzg|füfesächzg", "soixante-cinq",
     "sessantacinque", "sessantatschintg"),
    (100, "hundred|one hundred", "hundert|einhundert", "", "cent|cents", "cento", "tschient"),
    (1000, "thousand|one thousand", "tausend|eintausend", "tuusig|tausig", "mille", "mille",
     "milli"),
    (50_000, "fifty thousand", "fünfzigtausend", "füfzgtuusig|füfzgtausig", "cinquante mille",
     "cinquantamila", "tschuncanta milli"),
    (100_000, "hundred thousand|one hundred thousand",
     "hunderttausend|hundertausend|einhunderttausend", "hunderttuusig|hunderttausig",
     "cent mille", "centomila|cento mila", "tschient milli|tschientmilli"),
]
# No value of their own; read only so that they close a compound: "thirty-one", "trente et un".
PARTS = {"en": "one|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth",
         "fr": "et un|et une|et unième|deuxième|troisième|quatrième|cinquième|sixième"
               "|septième|huitième|neuvième"}
# "sei" is also "you are", "neuf" and "nov" also "new"; a plural unit of time tells them apart.
BEFORE_TIME = {"it": ("sei", "mesi|anni|settimane|giorni|ore"),
               "fr": ("neuf", "mois|ans|années|semaines|jours|heures"),
               "rm": ("nov", "mais|onns|emnas|dis|uras")}


class Found(NamedTuple):
    start: int
    end: int
    values: list
    kind: str  # "digits", "unit", or "word": a number word or a compound part


def spellings(lang: str) -> list[tuple[str, int | None]]:
    columns = [LANGS.index("de"), LANGS.index("gsw")] if lang == "gsw" else [LANGS.index(lang)]
    words = [(word, value) for value, *by_column in WORDS for column in columns
             for word in by_column[column].split("|") if word]
    parts = [(part, None) for part in PARTS.get(lang, "").split("|") if part]
    return [(unit, None) for unit in UNITS] + parts + words


def phrase_key(phrase: str) -> str:
    return JOIN.sub(" ", phrase.casefold())


def _pattern(lang: str) -> re.Pattern:
    guarded, units = BEFORE_TIME.get(lang, ("", ""))
    alternatives = []
    # Longest first, so "cent mille" wins over "cent" and "pour cent" over "cent".
    for phrase, _ in sorted(spellings(lang), key=lambda s: len(s[0]), reverse=True):
        regex = rf"(?:{JOIN.pattern})".join(map(re.escape, JOIN.split(phrase)))
        if phrase == guarded:
            regex += rf"(?=[{SPACES}]+(?:{units})(?!\w))"
        alternatives.append(regex)
    return re.compile(rf"(?<!\w)(?:{'|'.join(alternatives)})(?!\w)", re.IGNORECASE)


VOCABULARY = {lang: {phrase_key(s): v for s, v in spellings(lang)} for lang in LANGS}
PATTERNS = {lang: _pattern(lang) for lang in LANGS}


def numbers(text: str, lang: str) -> list[int | float]:
    digits = [Found(m.start(), m.end(), _read_token(*m.groups(), lang == "en"), "digits")
              for m in TOKEN.finditer(text)]
    # A word for thousand right after digits was read with them, as in "100 mila".
    words = [_word(m, VOCABULARY[lang]) for m in PATTERNS[lang].finditer(text)
             if not any(d.start <= m.start() < d.end for d in digits)]
    groups: list[list[Found]] = []
    for item in sorted(digits + words, key=lambda f: f.start):
        if groups and _joined(groups[-1][-1], item, text, lang):
            groups[-1].append(item)
        else:
            groups.append([item])
    return [value for group in groups if len(group) == 1 for value in group[0].values]


def _word(match: re.Match, table: dict) -> Found:
    key = phrase_key(match.group())
    value = table.get(key)  # None for a unit, a compound part or a case fold the table lacks
    kind = "unit" if key in UNITS else "word"
    return Found(match.start(), match.end(), [] if value is None else [value], kind)


def _joined(left: Found, right: Found, text: str, lang: str) -> bool:
    # Read word by word, "two hundred thousand" would state 2 and 100000, which it does not.
    if right.kind != "word" or left.kind == "unit" or not left.values:
        return False
    gap = text[left.end:right.start]
    if left.kind == "digits":
        return bool(right.values) and right.values[0] >= 100 and bool(JOIN.fullmatch(gap))
    after_hundred = lang == "en" and left.values[0] >= 100 and AND.fullmatch(gap)
    return bool(JOIN.fullmatch(gap) or after_hundred)


def _read_token(plus: str, token: str, thousand: str | None, closing: str | None,
                english: bool) -> list[int | float]:
    # A decimal that ends a sentence looks the same; outside English the date is more common.
    if closing and not english and DAY_MONTH.fullmatch(token):
        return [int(part) for part in token.split(".")]
    if plus or re.match(r"0[0-9]", token):
        parts = re.split(f"[{SPACES}]", token)
        values = [v for part in parts for v in _read_digits(part, english)]
    else:
        values = _read_digits(token, english)
    if thousand:
        scaled = Decimal(str(values[-1])) * 1000  # as 1.1 * 1000 is 1100.0000000000002
        values[-1] = int(scaled) if scaled == scaled.to_integral_value() else float(scaled)
    return values


def _read_digits(token: str, english: bool) -> list[int | float]:
    parts = SEPARATOR.split(token)
    digits, separators = parts[0::2], parts[1::2]
    values, head, grouper, point, dated = [], 0, None, None, False
    for k, sep in enumerate(separators, start=1):
        follows = separators[k] if k < len(separators) else None
        # A dot or comma followed by another one is part of a date such as 1.1.2024.
        decimal = sep in ".," and sep != grouper and follows not in (".", ",")
        if point is None and _joins_thousands(sep, digits[head], digits[k], grouper, follows,
                                              english):
            grouper = sep
        elif point is None and not dated and decimal:
            point = k
        else:  # neither grouping nor a decimal point: the separator ends a number
            values.append(_make_number(digits[head:k], point is not None))
            dated = dated or sep in ".,"
            head, grouper, point = k, None, None
    values.append(_make_number(digits[head:], point is not None))
    return values


def _joins_thousands(sep: str, head: str, group: str, grouper: str | None, follows: str | None,
                     english: bool) -> bool:
    if len(group) != 3 or not 1 <= len(head) <= 3 or head.startswith("0"):
        return False
    if grouper not in (None, sep):
        return False
    if sep in APOSTROPHES or sep in SPACES:
        return True
    return (sep == ",") == english or follows == sep or grouper == sep


def _make_number(parts: list[str], decimal: bool) -> int | float:
    # A decimal point is always followed by the number's last group.
    whole, fraction = (parts[:-1], parts[-1]) if decimal else (parts, "")
    if fraction.strip("0"):
        return float("".join(whole) + "." + fraction)
    return int("".join(whole))
