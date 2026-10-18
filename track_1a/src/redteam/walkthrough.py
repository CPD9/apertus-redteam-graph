"""Apertus conversations in the exact chat format of chat_template.json, and which answers a finding
shows as its walkthroughs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .answers import Answer

TEMPLATE = json.loads(Path(__file__).with_name("chat_template.json").read_text())
PLACEHOLDERS = re.compile("|".join(map(re.escape, TEMPLATE["placeholders"])))
MAX_LENGTH = 20000  # findings.schema limit for one walkthrough
QUOTE_MARKS = "\"'„“”«»‚‘’ "


def quotes_answer(quote: str, answer: str) -> bool:
    """The judge sometimes quotes the user's prompt or the reference, or stitches pieces together.
    A quote counts when its text up to the first ellipsis has at least 15 characters and appears
    verbatim in the answer, ignoring case, emphasis, spacing and outer quote marks."""
    def norm(text):
        return " ".join(text.lower().replace("*", "").split()).strip(QUOTE_MARKS)
    head = norm(re.split(r"\.\.\.|…", quote)[0])
    return len(head) >= 15 and head in norm(answer)


def render(user: str, answer: str, system: str | None = None) -> str:
    # Without a system prompt Apertus applies its built-in one, which the template already holds.
    shell = TEMPLATE["system_user_assistant" if system else "user_assistant"]
    # A few recorded answers end in NUL bytes from the server; they are not part of the text.
    answer = answer.replace("\x00", "")
    room = MAX_LENGTH - len(_fill(shell, system, user, ""))
    return _fill(shell, system, user, answer[:room])


def _fill(shell: str, system: str | None, user: str, answer: str) -> str:
    values = {"<<SYSTEM>>": system or "", "<<USER>>": user, "<<ASSISTANT>>": answer}
    # One pass, so a placeholder typed inside the user's text is never substituted.
    return PLACEHOLDERS.sub(lambda m: values[m.group(0)], shell)


def pick(answers: list[Answer], strength, limit: int = 10) -> list[Answer]:
    """Up to `limit` answers, one per variation and language, strongest first, preferring
    variations and languages not shown yet."""
    pool = sorted(answers, key=strength, reverse=True)
    chosen = []

    def repeats(answer: Answer) -> int:
        same_variation = sum(a.hypothesis == answer.hypothesis for a in chosen)
        same_language = sum(a.lang == answer.lang for a in chosen)
        return same_variation + same_language

    while pool and len(chosen) < limit:
        best = min(pool, key=repeats)  # min keeps the first of equals, which is the strongest
        chosen.append(best)
        pool = [a for a in pool if (a.hypothesis, a.lang) != (best.hypothesis, best.lang)]
    return chosen
