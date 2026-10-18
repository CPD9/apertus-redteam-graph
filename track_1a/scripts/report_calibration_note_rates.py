"""The calibration note's section 2: the counted rates corrected by Rogan-Gladen, why the
correction does not fit this reference, and what it cannot say about the order of the languages.
"""
from __future__ import annotations

from decimal import Decimal

from report_calibration_speech import ALL
from report_note import (grid_table, holds, listed, ratio, rounded, signed, span, spelled, spread,
                         two)

from redteam.numbers_in_text import LANGS

FEWEST = 5  # a per-language Se on fewer answers is too rough to name as an example


def estimate(t: dict) -> str:
    return f"{two(t['corrected'])} ({span(t['corrected_ci95'])})"


def change(value: float, ci: list) -> str:
    return f"{signed(two(value))} ({signed(two(ci[0]))} to {signed(two(ci[1]))})"


def rate_cells(t: dict) -> list[str]:
    return [f"{two(t['raw'])} ({span(t['raw_ci95'])})", two(t["unclipped"]), estimate(t)]


def table_rows(found: list[dict]) -> list[list]:
    rows = [[lang, *(cell for c in found for cell in rate_cells(c["per_lang"][lang]))]
            for lang in LANGS]
    rows.append([ALL, *(cell for c in found for cell in rate_cells(c[ALL]))])
    gaps = [c["rm_minus_en"] for c in found]
    rows.append(["rm − en", *(cell for d in gaps for cell in (
        change(d["raw"], d["raw_ci95"]), change(d["unclipped"], d["unclipped_ci95"]), "–"))])
    return rows


def misfit_lines(runs: dict) -> list[str]:
    below, sp, scaled, upper, widest = [], [], [], [], []
    for x in runs.values():
        c, accuracy = x["reference"]["corrected"], x["reference"]["accuracy"][ALL]
        langs = [lang for lang in LANGS if c["per_lang"][lang]["unclipped"] < 0]
        if langs:
            below.append(f"{x['label']} {listed(langs)}")
        sp.append(two(Decimal(1) - Decimal(str(accuracy["specificity"]["rate"]))))
        scaled.append(f"{c['rm_minus_en']['raw']}/{accuracy['youden']}")
        upper.append(c["rm_minus_en"]["unclipped_ci95"][1])
        low = min(t["unclipped_ci95"][0] for t in [*c["per_lang"].values(), c[ALL]])
        widest.append(f"{rounded(low, 1)} ({x['label']})")
    holds(bool(below), "the correction gives impossible values with this reference")
    holds(min(upper) > 1, "the corrected gap's upper bounds exceed any difference of two rates")
    return ["**The correction cannot be used with this reference.**", "",
            f"- **Impossible values.** p is below 0 for {' and for '.join(below)}, because the "
            f"counted rate there is below 1 − Sp ({listed(sp)}). That means the Se and Sp of the "
            "numeric subset do not carry over to these cells, a misspecification and not only "
            "imprecision. Clipping turns these values into zeros.",
            "- **The gap is scaled, not removed.** With one Se and Sp per run, the corrected "
            "rm − en is the counted gap divided by Se + Sp − 1 "
            f"({listed(scaled)}). Its upper bounds, {listed(two(u) for u in upper)}, are larger "
            "than any difference of two rates can be. No corrected gap is built from clipped "
            "rates.",
            f"- **Width.** Unclipped intervals reach {listed(widest)}, from draws where "
            "Se + Sp − 1 is close to 0.", ""]


def without_lines(n: dict) -> list[str]:
    lines, fitted = [f"*Post hoc check: the reference without {listed(n['unsure'])}.*", ""], []
    for x in n["runs"].values():
        accuracy, c = x["without_unsure"]["accuracy"][ALL], x["without_unsure"]["corrected"]
        opening = f"- **{x['label']}.** Sp becomes {ratio(accuracy['specificity'])}"
        youden = (f"(Se + Sp − 1 = {two(accuracy['youden'])}, {c[ALL]['void_draws']} draws "
                  "left out)")
        below = sum(t["unclipped"] < 0 for t in c["per_lang"].values())
        if all(0 <= t["unclipped"] <= 1 for t in [*c["per_lang"].values(), c[ALL]]):
            fitted.append(x)
            gap = c["rm_minus_en"]
            lines.append(f"{opening} and Se {ratio(accuracy['sensitivity'])} {youden}. All point "
                         f"estimates then fall in [0, 1]: en {estimate(c['per_lang']['en'])}, rm "
                         f"{estimate(c['per_lang']['rm'])}, all {estimate(c[ALL])}, and rm − en "
                         f"{change(gap['unclipped'], gap['unclipped_ci95'])}.")
        else:
            holds(below > len(LANGS) / 2, "without it, most languages fall below 0 on a run")
            lines.append(f"{opening} from {accuracy['specificity']['hypotheses']} hypotheses "
                         f"{youden}. {spelled(below).capitalize()} of the {spelled(len(LANGS))} "
                         "languages fall below 0, so nothing can be read.")
    holds(len(fitted) == 1 and any(t["unclipped"] < 0 for t in
                                   fitted[0]["reference"]["corrected"]["per_lang"].values()),
          "one hypothesis decides whether one run's correction fits")
    return [*lines, "", f"One hypothesis decides whether the {fitted[0]['label']} correction "
            "even fits.", ""]


def order_lines(runs: dict) -> list[str]:
    examples = []
    for x in runs.values():
        se = {lang: t["sensitivity"] for lang, t in x["reference"]["accuracy"]["per_lang"].items()
              if t["sensitivity"]["n"] >= FEWEST}
        low = min(se, key=lambda lang: se[lang]["rate"])
        high = max(se, key=lambda lang: se[lang]["rate"])
        holds(se[low]["rate"] < se[high]["rate"], "the per-language Se point estimates differ")
        examples.append(f"{x['label']} {low} {ratio(se[low])} against {high} {ratio(se[high])}")
    return ["**Language order.** A correction with one Se and Sp is monotone in q, so by "
            "construction it cannot reorder the languages. That is a property of the method, not "
            f"evidence. The per-language Se point estimates differ ({'; '.join(examples)}). So "
            "judge error that differs by language could reorder them, and at this n that is "
            "untested.", ""]


def corrected(n: dict) -> list[str]:
    runs, draws = n["runs"], n["bootstrap"]["draws"]
    found = [x["reference"]["corrected"] for x in runs.values()]
    labels = [x["label"] for x in runs.values()]
    clusters = [f"{sum(c['hypotheses_with_and_without_labels'])} on the {label}"
                for c, label in zip(found, labels)]
    void = [f"{found[0][ALL]['void_draws']} of {draws} on the {labels[0]}",
            *(f"{c[ALL]['void_draws']} on the {label}" for c, label in zip(found[1:], labels[1:]))]
    labelled = spread([x["reference"]["hypotheses"] for x in runs.values()], "or")
    return ["## 2. Counted rate corrected by Rogan–Gladen", "",
            "The correction is p = (q + Sp − 1) / (Se + Sp − 1). Each run's pooled Se and Sp are "
            "applied to its counted rate q over every hypothesis with answers: "
            f"{listed(clusters)}. This assumes that Se and Sp from {labelled} numeric hypotheses "
            "carry over to the other hypotheses, to every language, and to the \"both\" answers. "
            "p is shown unclipped and then clipped to [0, 1], since clipping hides a misfit. "
            "Intervals resample hypotheses, with and without labels apart. A draw with "
            f"Se + Sp ≤ 1 cannot be corrected and is left out: {listed(void)}.", "",
            *grid_table(["", *(f"{label} {column}" for label in labels
                               for column in ("counted", "p", "p clipped"))], table_rows(found)),
            *misfit_lines(runs), *without_lines(n), *order_lines(runs)]
