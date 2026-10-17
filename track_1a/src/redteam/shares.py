"""Rates of answers: the share that counts (answers.Answer.confirmed) with its Wilson interval,
overall and per language."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .stats import wilson

if TYPE_CHECKING:  # answers imports this module to count its answers
    from .answers import Answer


@dataclass(frozen=True)
class Share:
    k: int
    n: int

    @property
    def rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def ci95(self) -> tuple[float, float]:
        return wilson(self.k, self.n)

    def brief(self) -> dict:
        return {"rate": round(self.rate, 3), "ci95": [round(x, 3) for x in self.ci95],
                "k": self.k, "n": self.n}


def share(answers: list[Answer]) -> Share:
    return Share(sum(a.confirmed for a in answers), len(answers))


def per_lang(answers: list[Answer], langs: list[str]) -> dict[str, Share]:
    return {lang: share([a for a in answers if a.lang == lang]) for lang in langs}


def rates(answers: list[Answer], langs: list[str]) -> dict[str, float]:
    return {lang: round(s.rate, 3) for lang, s in per_lang(answers, langs).items()}


def of(answers: list[Answer], ids) -> list[Answer]:
    return [a for a in answers if a.hypothesis in ids]
