"""The text and numbers of one themed finding, written from the theme's measurements."""
from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from . import clusters, lang_profile
from .graph import Config
from .answers import Answer, Run
from .models import model_id, versioned
from .scribe import MAX_OUTPUT_TOKENS
from .shares import of, per_lang, rates, share
from .walkthrough import QUOTE_MARKS, quotes_answer

if TYPE_CHECKING:  # group imports this module to assemble its findings
    from .group import Measured, Replica

STATED = "stated the error as fact"  # what a counted answer did, unless the theme says otherwise
# The language each of these is most easily mistaken for, as the stimulus audit pairs them.
PAIRED = {"gsw": ("de", "Standard German"), "rm": ("it", "Italian")}


def pct(x: float) -> str:
    return f"{x:.0%}"


def interval(ci: list[float]) -> str:
    return f"95% CI {pct(ci[0])}-{pct(ci[1])}"


def gap(low: float, high: float) -> str:
    """The premise-minus-neutral interval, in percentage points."""
    return (f"(premise minus neutral: {round(low * 100):+d} to {round(high * 100):+d} points, "
            "95% CI paired by variation and language, never narrower than Newcombe's; biased "
            "upward, as the variations were kept for erring on these answers)")


def variations(n: int) -> str:
    return "1 variation" if n == 1 else f"{n} variations"


def stated(m: Measured) -> str:
    return m.theme.get("stated", STATED)


def join(parts: list[str]) -> str:
    """The non-empty parts as one text, never cut: the schema check rejects one that is too long."""
    return " ".join(filter(None, parts))


def fitting(parts: list[str], limit: int) -> list[str]:
    """The leading non-empty parts whose space-joined text stays within limit characters."""
    kept, length = [], -1
    for part in filter(None, parts):
        length += 1 + len(part)
        if length > limit:
            break
        kept.append(part)
    return kept


def contrast(m: Measured, langs: list[str]) -> str:
    """The neutral questions are written from each reference, so a theme whose questions differ
    from the premise questions in scope gives a caveat instead of a reading. The reading rests on
    the premise-minus-neutral interval, paired by variation and language."""
    premise, neutral = m.control
    spread = interval(clusters.interval(m.neutral, langs))
    said = (f"Asked neutral questions written from the same references, without a false premise, "
            f"it erred in {pct(neutral.rate)} of answers ({spread}) against {pct(premise.rate)} "
            "with it")
    if caveat := m.theme.get("control_caveat"):
        return f"{said}. {caveat}"
    low, high = clusters.difference(m.answers, m.neutral, langs)
    if low > 0:
        reading = "so the false premise makes the error more likely"
    elif high < 0:
        reading = "so Apertus lacks these facts even when nobody suggests a wrong one"
    else:
        reading = "a difference within chance over these variations and languages"
    return f"{said}, {reading} {gap(low, high)}."


def asked(m: Measured) -> list[Answer]:
    """The answers to the variations the neutral-question control asked too."""
    return of(m.answers, {a.hypothesis for a in m.neutral})


def replication(r: Replica, said: str = STATED) -> str:
    failed = f", {len(r.failed)} could not be measured (run error)" if r.failed else ""
    answers = (f"; {r.share.k} of {r.share.n} verified answers ({pct(r.share.rate)}) {said}"
               if r.share.n else "")
    return (f"With {r.run.model} as target, {len(r.reproduced)} of "
            f"{variations(len(r.measured))} reproduced{failed}{answers}.")


def written_in(m: Measured, lang: str) -> str:
    """For Swiss German and Romansh, how many counted answers the word list of lang_profile reads
    as the paired language. Named only when most are, as the rate then says more about replies in
    that language than in the one asked."""
    if lang not in PAIRED:
        return ""
    other, name = PAIRED[lang]
    counted = [a for a in m.answers if a.lang == lang and a.confirmed]
    k = sum(lang_profile.profile(a.text).lang == other for a in counted)
    return f" ({k} of {len(counted)} counted in {name})" if 2 * k > len(counted) else ""


def overview(m: Measured, run: Run) -> str:
    pooled = share(m.answers)
    by_lang = "By language, one prompt each: " if len(m.ids) == 1 else "By language: "
    return join([
        m.theme["overview"].format(subjects=m.subjects),
        f"Measured on {run.model}: {pooled.k} of {pooled.n} verified answers ({pct(pooled.rate)}, "
        f"{interval(clusters.interval(m.answers, run.langs))}) {stated(m)} by the judge's count, "
        f"from {variations(len(m.ids))} asked in {len(run.langs)} languages with "
        f"{len(run.seeds)} sampling seeds each.",
        by_lang + ", ".join(f"{lang} {pct(s.rate)}{written_in(m, lang)}"
                            for lang, s in per_lang(m.answers, run.langs).items()) + ".",
        contrast(m, run.langs) if m.control else "",
        replication(m.replica, stated(m)) if m.replica and m.replica.measured else "",
    ])


def quote(m: Measured, hypothesis: str) -> str:
    """The judge's quote of the error from the most severe confirmed answer it quotes verbatim;
    of equally severe ones, from the language where the variation reproduced most."""
    answers = of(m.answers, {hypothesis})
    rate = {a.lang: share([b for b in answers if b.lang == a.lang]).rate for a in answers}
    candidates = [a for a in answers if a.confirmed and quotes_answer(a.evidence, a.text)]
    best = max(candidates, key=lambda a: (a.severity, rate[a.lang]), default=None)
    return f'[{best.lang}, {hypothesis}] "{best.evidence.strip(QUOTE_MARKS)}"' if best else ""


def behaviour(m: Measured, refs: dict) -> tuple[str, str]:
    """desired_behavior and observed_behavior, both for the most reproduced variations that fit."""
    many = len(m.ids) > 1
    order = ", most reproduced variation first" if many else ""
    sources = "references state" if many else "reference states"
    lead = f"{m.theme['desired']} The facts, as the judge's {sources} them{order}:"
    rules = fitting([f"[{h}] {refs[h]['reference']}" for h in m.ids], 1000 - len(lead) - 1)
    pooled = share(m.answers)
    observed = fitting([f"{pooled.k} of {pooled.n} verified answers {stated(m)}. What Apertus "
                        f"said, as the judge quoted it{order}:",
                        *(quote(m, h) for h in m.ids[:len(rules)])], 1000)
    return " ".join([lead, *rules]), " ".join(observed)


def steps(m: Measured, run: Run, control_id: str) -> list[str]:
    system = f" --system {shlex.quote(run.system)}" if run.system else ""
    selection = "--only " + " ".join(m.ids) + system
    judge = model_id(run.judge)
    served = f"{judge} under the name {run.judge}" if judge != run.judge else judge
    rebuild = (f"--run {run.id}" + (f" --control {control_id}" if m.control else "")
               + (f" --replication {m.replica.run.id}" if m.replica else ""))
    return [
        "From track_1a/, replay the recorded answers without a GPU (Python 3.12, standard library "
        f"only): LLM_NAME={run.model} RED_LLM_NAME={run.judge} PYTHONPATH=src python3 -m "
        f"redteam.run --replay {selection}",
        f"Or live: serve {run.model} on 127.0.0.1:8000 and {served} on 127.0.0.1:8002 with vLLM, "
        f"as in infra/runpod/README.md, then: PYTHONPATH=src python3 -m redteam.run {selection}",
        f"runs/{run.id}/events.jsonl (data/runs/ for the runs shipped with the repository) logs "
        "every step of the graph. The full answers and verdicts that decide what counts are "
        "replayed by redteam.answers from the LLM cache in data/. Neutral control of a run made on "
        "this machine (an id in runs/; the recorded runs ship their control.json): "
        "PYTHONPATH=src python3 -m redteam.control --run <run_id>",
        f"Rebuild this file: PYTHONPATH=src python3 -m redteam.group {rebuild} --write",
    ]


def parameters(m: Measured, run: Run, control_id: str) -> dict:
    pooled = share(m.answers)
    judge = model_id(run.judge)
    out = {"temperature": Config.temperature, "max_output_tokens": MAX_OUTPUT_TOKENS,
           "harness_backend": run.backend, "harness_red_model": judge,
           **versioned("harness_red_model_version", judge),
           "harness_system_prompt": run.system,
           "harness_run_id": run.id, "harness_langs": run.langs, "harness_seeds": run.seeds,
           "harness_reproduction_rates": rates(m.answers, run.langs),
           "harness_overall_rate": round(pooled.rate, 3),
           "harness_overall_ci95": clusters.interval(m.answers, run.langs),
           "harness_ci95_method": clusters.METHOD,
           "harness_flagged_rate": round(sum(a.flagged for a in m.answers) / len(m.answers), 3),
           "harness_variations": [{"id": h, **m.share_of(h).brief(),
                                   "rates": rates(of(m.answers, {h}), run.langs)} for h in m.ids]}
    if m.control:
        out["harness_control"] = {"run_id": control_id,
                                  "premise": clusters.brief(asked(m), run.langs),
                                  "neutral": clusters.brief(m.neutral, run.langs),
                                  "premise_minus_neutral_ci95": clusters.difference(
                                      m.answers, m.neutral, run.langs)}
    if m.replica:
        r = m.replica
        measured = of(r.run.answers, r.measured)
        counted = clusters.brief(measured, r.run.langs) if measured else r.share.brief()
        out["harness_replication"] = {"model": r.run.model, "run_id": r.run.id, **counted,
                                      "variations_reproduced": r.reproduced,
                                      "variations_measured": r.measured,
                                      "variations_failed": r.failed}
    return out
