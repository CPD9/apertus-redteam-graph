"""The per-hypothesis sections of numbers.json: the canonical run's language heatmap, premise
against neutral question, and bank 2 on the 70B counted one hypothesis at a time."""
from __future__ import annotations

from .checks import Check, rounded
from .rates import Share, by_lang, share
from .runs import Run, Verdict
from .themes import BAR, family

VERIFIED = {"finding", "not_reproducible"}  # the verifier finished, whatever the judge's flags


def heatmap_rows(run: Run) -> list[dict]:
    rows = []
    for h in run.logged_n:
        cells = by_lang(run.of({h}), run.langs)
        rates = [s.rate for s in cells.values()]
        overall = share(run.of({h})).rate
        rows.append({"id": h, "reproduced": overall >= BAR,
                     "gap": round(max(rates) - min(rates), 4), "overall": round(overall, 4),
                     "per_lang": {lang: [s.k, s.n, round(s.rate, 4)] for lang, s in cells.items()}})
    return sorted(rows, key=lambda r: (-r["gap"], -r["overall"], r["id"]))


def heatmap_checks(at: str, stated: dict, run: Run) -> list[Check]:
    rows = heatmap_rows(run)
    said = {row["id"]: row for row in stated.get("rows", [])}
    checks = [Check(f"{at}.run", stated.get("run"), run.id),
              Check(f"{at}.langs", stated.get("langs"), run.langs),
              Check(f"{at}.answers_per_cell", stated.get("answers_per_cell"),
                    sorted({n for row in rows for _, n, _ in row["per_lang"].values()})),
              Check(f"{at}.rows order", list(said), [row["id"] for row in rows])]
    for row in rows:
        where, stated_row = f"{at}.rows[{row['id']}]", said.get(row["id"], {})
        checks += [Check(f"{where}.{key}", stated_row.get(key), row[key])
                   for key in ("reproduced", "gap", "overall")]
        checks += [Check(f"{where}.per_lang.{lang} [k, n, rate]",
                         [stated_row.get("per_lang", {}).get(lang, {}).get(key)
                          for key in ("k", "n", "rate")], cell)
                   for lang, cell in row["per_lang"].items()]
    return checks


def control_shares(run: Run, neutral: list[Verdict]) -> dict[str, tuple[Share, Share]]:
    """Premise and neutral share of every hypothesis the control asked and the run replayed."""
    asked = dict.fromkeys(v.hypothesis for v in neutral)
    return {h: (share(run.of({h})), share(v for v in neutral if v.hypothesis == h))
            for h in asked if h not in run.unreplayed}


def premise_rows(run: Run, neutral: list[Verdict], themes: list[dict]) -> tuple[list, list]:
    """The reproduced hypotheses with a control, minus those left out after reading, the
    largest premise-minus-neutral gap first; and those left out."""
    shares = control_shares(run, neutral)
    left_out = sorted({h for t in themes for h in t.get("excluded", {})} & set(shares))
    rows = [(h, p, n) for h, (p, n) in shares.items() if p.rate >= BAR and h not in left_out]
    return sorted(rows, key=lambda row: (-round(row[1].rate - row[2].rate, 4), row[0])), left_out


def caveat(themes: list[dict], hypothesis: str) -> str | None:
    return next((t for t in themes if family(t, hypothesis)), {}).get("control_caveat")


def premise_checks(at: str, stated: dict, run: Run, neutral: list[Verdict], themes: list[dict],
                   titles: dict[str, str]) -> list[Check]:
    rows, left_out = premise_rows(run, neutral, themes)
    said = {row["id"]: row for row in stated.get("rows", [])}
    checks = [Check(f"{at}.run", stated.get("run"), run.id),
              Check(f"{at}.excluded", stated.get("excluded"), left_out),
              Check(f"{at}.rows order", list(said), [h for h, _, _ in rows])]
    for h, p, n in rows:
        where, row = f"{at}.rows[{h}]", said.get(h, {})
        checks += [Check(f"{where}.label", row.get("label"), titles.get(h, h)),
                   Check(f"{where}.control_caveat", row.get("control_caveat"), caveat(themes, h)),
                   Check(f"{where}.premise_rate", row.get("premise_rate"), round(p.rate, 4)),
                   Check(f"{where}.premise_ci95", row.get("premise_ci95"), rounded(p.wilson, 4)),
                   Check(f"{where}.premise_n", row.get("premise_n"), p.n),
                   Check(f"{where}.neutral_rate", row.get("neutral_rate"), round(n.rate, 4)),
                   Check(f"{where}.neutral_ci95", row.get("neutral_ci95"), rounded(n.wilson, 4)),
                   Check(f"{where}.neutral_n", row.get("neutral_n"), n.n),
                   Check(f"{where}.gap", row.get("gap"), round(p.rate - n.rate, 4))]
    return checks


def bank_rows(run: Run) -> list[dict]:
    rows = []
    for h in run.hypotheses:
        s, status = share(run.of({h})), run.outcome.get(h, "unfinished")
        rows.append({"id": h, "status": status, "k": s.k, "n": s.n, "rate": round(s.rate, 4),
                     "reproduced": status in VERIFIED and s.rate >= BAR})
    return rows


def bank_checks(at: str, stated: dict, run: Run, titles: dict[str, str]) -> list[Check]:
    said = {row["id"]: row for row in stated.get("rows", [])}
    rows = bank_rows(run)
    checks = [Check(f"{at}.run", stated.get("run"), run.id),
              Check(f"{at}.model", stated.get("model"), run.model),
              Check(f"{at}.bar", stated.get("bar"), BAR, constant=True),
              Check(f"{at}.unreplayed", stated.get("unreplayed"), run.unreplayed),
              Check(f"{at}.rows order", list(said), [row["id"] for row in rows])]
    for row in rows:
        where, stated_row = f"{at}.rows[{row['id']}]", said.get(row["id"], {})
        checks.append(Check(f"{where}.title", stated_row.get("title"), titles.get(row["id"])))
        checks += [Check(f"{where}.{key}", stated_row.get(key), row[key])
                   for key in ("status", "k", "n", "rate", "reproduced")]
    return checks
