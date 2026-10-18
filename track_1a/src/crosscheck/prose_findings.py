"""Numbers in the report's finding paragraphs, the bank 2 paragraph and the lessons: what single
variations, the speech clips, bank 2, the mitigation run and the second judge come to."""
from __future__ import annotations

from .agreement import kappa
from .audit import Audit
from .checks import Check, pct, present, rounding, stated
from .figures import bank_rows
from .prose import R, rate
from .rates import share
from .speech import DIALECTS, unrelated_everywhere


def all_or_count(verdicts) -> int | str:
    """How a paragraph says "all n answers": n when every answer counts, else "k of n"."""
    s = share(verdicts)
    return s.n if s.k == s.n else f"{s.k} of {s.n}"


def text_findings(text: str, audit: Audit) -> list[Check]:
    at, canonical = f"{R} findings 1-4", audit.runs["canonical"]
    civic, private = audit.themes["civic_sycophancy"], audit.themes["private_person_fabrication"]
    safety, pension = audit.themes["safety_knowledge_gaps"], audit.themes["pension_rules"]
    signatures = canonical.of({"vote_initiative_signatures"})
    toxinfo = canonical.of({"emergency_145_toxinfo"})
    deductible_en = [v for v in canonical.of({"kvg_deductible_range"}) if v.lang == "en"]
    privacy = canonical.of({"privacy_fabricated_person"})
    return [
        present(at, text, "on postal voting, was left out after reading",
                "vote_postal_deadline" in civic.excluded),
        *stated(at, text, r"agrees in \d+ of the (\d+) German, Swiss German, French, Italian and "
                r"Romansh answers",
                {"non-English answers": sum(v.lang != "en" for v in signatures)}),
        present(at, text, "and in none of the English ones",
                share(v for v in signatures if v.lang == "en").k == 0,
                "'and in none of the English ones' (checked: no English answer counted)"),
        *stated(at, text, r"it agrees in all (\d+) answers",
                {"suffrage": all_or_count(canonical.of({"hist_womens_suffrage_1971"}))}),
        *stated(at, text, r"Neutral questions written from the same references are answered "
                r"wrongly (\d+)% of the time", {"civic neutral %": pct(share(civic.neutral).rate)}),
        present(at, text, "the 8B declines in English",
                share(v for v in privacy if v.lang == "en").k == 0,
                "'the 8B declines in English' (checked: no English answer counted)"),
        *stated(at, text, r"confirms it in all (\d+) answers in the other five languages",
                {"privacy non-English": all_or_count(v for v in privacy if v.lang != "en")}),
        *stated(at, text, r"The 70B mostly resists \((\d+)%\)",
                {"privacy on 70B %": pct(share(private.replica.verdicts).rate)}),
        present(at, text, "it confirms 112 when the user suggests it, in every language and seed",
                share(toxinfo).k == share(toxinfo).n,
                "'it confirms 112 ... in every language and seed' (checked: every answer "
                "counted)"),
        *stated(at, text, r"names 144 \(ambulance\) in all (\d+) neutral answers",
                {"toxinfo neutral": all_or_count(v for v in safety.neutral
                                                 if v.hypothesis == "emergency_145_toxinfo")}),
        *stated(at, text, r"no cap on co-payments \((\d+) of (\d+) answers",
                {"deductible en k": share(deductible_en).k,
                 "deductible en n": share(deductible_en).n}),
        *stated(at, text, r"Neutral questions fail as often \((\d+)%\)",
                {"safety neutral %": pct(share(safety.neutral).rate)}),
        *stated(at, text, r"wrong in (\d+)% of answers \(70B: (\d+)%\), and asked neutrally as "
                r"often \((\d+)%", {"pension %": pct(share(pension.verdicts).rate),
                                    "pension on 70B %": pct(share(pension.replica.verdicts).rate),
                                    "pension neutral %": pct(share(pension.neutral).rate)}),
    ]


def speech(text: str, audit: Audit) -> list[Check]:
    at, s = f"{R} finding 5", audit.speech
    a = s.share("apertus")
    low, high = s.intervals["apertus"]
    best, worst = s.order[-1], s.order[0]
    return [
        *stated(at, text, r"On (\d+) SwissDial clips \((\d+) dialects × (\d+) sentences",
                {"clips": a.n, "dialects": len(s.order), "sentences": s.sentences}),
        *stated(at, text, r"did not say in (\d+)% \(95% CI \d+–\d+\), from (\d+)% of (\w+) to "
                r"(\d+)% of (\w+) clips", {"unrelated %": pct(a.rate),
                                           "best %": pct(s.share("apertus", best).rate),
                                           "best dialect": DIALECTS[best],
                                           "worst %": pct(s.share("apertus", worst).rate),
                                           "worst dialect": DIALECTS[worst]}),
        *stated(at, text, r"did not say in \d+% \(95% CI (\d+)–(\d+)\)",
                {"ci95 low": low.percent, "ci95 high": high.percent}, rounding(0)),
        *stated(at, text, r"the same judge rates (\d+)% of its outputs unrelated and (\d+)% as "
                r"keeping the meaning", {"whisper unrelated %": pct(s.share("whisper").rate),
                                         "whisper same %":
                                             pct(s.share("whisper", None, "same").rate)}),
        *stated(at, text, r"(\w+) of the (\d+) sentences were judged unrelated in all eight",
                {"everywhere": len(unrelated_everywhere(s.clips["apertus"])),
                 "sentences": s.sentences}),
    ]


def counted(rows: dict[str, dict], hypothesis: str) -> dict:
    return {f"{hypothesis} k": rows[hypothesis]["k"], f"{hypothesis} n": rows[hypothesis]["n"]}


def bank2(text: str, audit: Audit) -> list[Check]:
    at = f"{R} bank 2"
    rows = {row["id"]: row for row in bank_rows(audit.runs["bank2"])}
    return [
        *stated(at, text, r"reproduces (\w+) more hypotheses",
                {"reproduced": sum(row["reproduced"] for row in rows.values())}),
        *stated(at, text, r"first year of work \((\d+) of (\d+) answers count\)",
                counted(rows, "work_sick_pay_first_year")),
        *stated(at, text, r"new and professional drivers \((\d+) of (\d+)\)",
                counted(rows, "traffic_bac_probation_professional")),
        *stated(at, text, r"the ban on radar warners \((\d+) of (\d+)\)",
                counted(rows, "traffic_radar_warning_ban")),
        *stated(at, text, r"(\w+) of its (\d+) hypotheses stopped with an error",
                {"errors": sum(row["status"] == "error" for row in rows.values()),
                 "hypotheses": len(rows)}),
        *stated(at, text, r"data breach notification, had (\d+) of (\d+) answers counted",
                counted(rows, "data_protection_breach_notification")),
    ]


def lessons(text: str, audit: Audit) -> list[Check]:
    at, c = f"{R} lessons", audit.mitigation
    first, second = audit.agreement["canonical"], audit.agreement["target70"]
    flagged = sum(a for a, _ in first.pairs)
    both = sum(a and b for a, b in first.pairs)
    return [
        present(at, text, audit.runs["mitigation"].system, True,
                "the system prompt of the mitigation run"),
        *stated(at, text, r"on the (\d+) retested hypotheses from (\d+)% to (\d+)% \(Romansh "
                r"(\d+)% to (\d+)%\), but English rose from (\d+)% to (\d+)%",
                {"retested": len(c.done),
                 **{f"{key} {name} %": rate(c, key, arm)
                    for key in ("all", "rm", "en")
                    for arm, name in enumerate(("before", "after"))}}),
        *stated(at, text, r"On the 8B run's (\d+) \*attack-loop answers\*",
                {"8B attack-loop answers": first.phase("probe")}),
        *stated(at, text, r"it flagged (\d+) of the (\d+) the main judge flagged \((\d+)%\), yet "
                r"it flags (\d+)% of all answers",
                {"both flagged": both, "main flagged": flagged, "share %": pct(both / flagged),
                 "second flags %": pct(sum(b for _, b in first.pairs) / len(first.pairs))}),
        *stated(at, text, r"Cohen's κ, agreement beyond what chance gives, is only (\d\.\d+)",
                {"8B kappa": round(kappa(first.pairs), 2)}),
        *stated(at, text, r"On the 70B run it judged (\d+) answers, the (\d+) verifier answers "
                r"counted above plus (\d+) attack-loop answers: κ (\d\.\d+)",
                {"70B judged": len(second.pairs), "verifier": second.phase("verifier"),
                 "attack loop": second.phase("probe"),
                 "70B kappa": round(kappa(second.pairs), 2)}),
    ]
