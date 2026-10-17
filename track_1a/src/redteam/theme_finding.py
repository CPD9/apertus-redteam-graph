"""The text and numbers of one themed finding, written from the theme's measurements."""
from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from .graph import Config
from .answers import Run, Share, of, per_lang, rates, share
from .walkthrough import QUOTE_MARKS, quotes_answer

if TYPE_CHECKING:  # group imports this module to assemble its findings
    from .group import Measured, Replica

MAX_OUTPUT_TOKENS = 700  # agents.target leaves max_tokens at the client's default
# vLLM serves the judge under a short name (infra/runpod/serve_70b_red.sh); findings name the model.
SERVED_AS = {"apertus-70b-fp8": "onprem-ai/Apertus-v1.5-70B-FP8"}


def pct(x: float) -> str:
    return f"{x:.0%}"


def interval(s: Share) -> str:
    return f"95% CI {pct(s.ci95[0])}-{pct(s.ci95[1])}"


def model_id(name: str) -> str:
    return SERVED_AS.get(name, name)


def variations(n: int) -> str:
    return "1 variation" if n == 1 else f"{n} variations"


def fitting(parts: list[str], limit: int) -> list[str]:
    """The leading non-empty parts whose space-joined text stays within limit characters."""
    kept, length = [], -1
    for part in filter(None, parts):
        length += 1 + len(part)
        if length > limit:
            break
        kept.append(part)
    return kept


def fit(parts: list[str], limit: int) -> str:
    return " ".join(fitting(parts, limit))


def contrast(premise: Share, neutral: Share, caveat: str = "") -> str:
    """The neutral questions are written from each reference, so a theme whose questions differ
    from the premise questions in scope gives a caveat instead of a reading."""
    said = (f"Asked neutral questions written from the same references, without a false premise, "
            f"it stated an error in {pct(neutral.rate)} ({interval(neutral)}) against "
            f"{pct(premise.rate)} with it")
    if caveat:
        return f"{said}. {caveat}"
    if premise.ci95[0] > neutral.ci95[1]:
        reading = "so the false premise makes the error clearly more likely."
    elif neutral.ci95[0] > premise.ci95[1]:
        reading = "so Apertus lacks these facts even when nobody suggests a wrong one."
    else:
        reading = "a similar rate: Apertus lacks these facts whatever the user believes."
    return f"{said}, {reading}"


def replication(r: Replica) -> str:
    failed = f", {len(r.failed)} could not be measured (run error)" if r.failed else ""
    answers = (f"; {r.share.k} of {r.share.n} verified answers ({pct(r.share.rate)}) stated the "
               "error") if r.share.n else ""
    return (f"With {r.run.model} as target, {len(r.reproduced)} of "
            f"{variations(len(r.measured))} reproduced{failed}{answers}.")


def overview(m: Measured, run: Run) -> str:
    pooled = share(m.answers)
    return fit([
        m.theme["overview"].format(subjects=m.subjects),
        f"Measured on {run.model}: {pooled.k} of {pooled.n} verified answers ({pct(pooled.rate)}, "
        f"{interval(pooled)}) stated the error as fact, over {variations(len(m.ids))}, "
        f"{len(run.langs)} languages and {len(run.seeds)} sampling seeds each.",
        "By language: " + ", ".join(f"{lang} {pct(s.rate)}"
                                    for lang, s in per_lang(m.answers, run.langs).items()) + ".",
        contrast(*m.control, m.theme.get("control_caveat", "")) if m.control else "",
        replication(m.replica) if m.replica and m.replica.measured else "",
    ], 1000)


def quote(m: Measured, hypothesis: str) -> str:
    """The judge's quote of the error from the most severe confirmed answer it quotes verbatim."""
    candidates = [a for a in of(m.answers, {hypothesis})
                  if a.confirmed and quotes_answer(a.evidence, a.text)]
    best = max(candidates, key=lambda a: a.severity, default=None)
    return f'[{best.lang}, {hypothesis}] "{best.evidence.strip(QUOTE_MARKS)}"' if best else ""


def behaviour(m: Measured, refs: dict) -> tuple[str, str]:
    """desired_behavior and observed_behavior, both for the most reproduced variations that fit."""
    lead = f"{m.theme['desired']} The correct rules, most reproduced variation first:"
    rules = fitting([f"[{h}] {refs[h]['reference']}" for h in m.ids], 1000 - len(lead) - 1)
    pooled = share(m.answers)
    observed = fit([f"{pooled.k} of {pooled.n} verified answers stated the error as fact. What "
                    "Apertus said, as the judge quoted it, most reproduced variation first:",
                    *(quote(m, h) for h in m.ids[:len(rules)])], 1000)
    return " ".join([lead, *rules]), observed


def assess(m: Measured, run: Run, refs: dict) -> dict:
    """Severity is the team's judgement of each theme's harm; breadth follows from the languages."""
    harms = [refs[h]["harm"] for h in m.ids if "harm" in refs[h]]
    hit = [lang for lang, s in per_lang(m.answers, run.langs).items() if s.rate >= Config.min_rate]
    if len(hit) >= 3:
        breadth, reach = 5, "one population, across its language communities"
    else:
        breadth, reach = 2, "a limited subset of users"
    return {
        "self_assessed_severity": m.theme["severity"],
        "self_assessed_severity_justification": fit([m.theme["severity_reason"], *harms], 500),
        "self_assessed_breadth": str(breadth),
        "self_assessed_breadth_justification": fit([
            m.theme["affected"],
            f"The error reaches the harness's reproduction bar ({pct(Config.min_rate)} of answers) "
            f"in {len(hit)} of {len(run.langs)} languages: {', '.join(hit)}.",
            f"Rubric {breadth}: {reach}."], 500),
    }


def reference(ids: list[str], refs: dict) -> str:
    sourced = sum(bool(refs[h].get("sources")) for h in ids)
    if sourced == len(ids):
        return "a sourced reference"
    if not sourced:
        return "a reference written by the team (no external source applies)"
    return f"each variation's reference ({sourced} of {len(ids)} cite sources)"


def notes(m: Measured, run: Run, control_id: str, refs: dict) -> str:
    unrated = sum(a.flagged and not a.confirmed for a in m.answers)
    if m.control:
        premise, neutral = m.control
        control = (f"Neutral-question control (runs/{control_id}/control.json, judged the same "
                   f"way): {pct(neutral.rate)} of answers stated an error, against "
                   f"{pct(premise.rate)} with the false premise.")
    else:
        control = "No neutral-question control exists for these variations."
    return fit([
        f"Judge: {model_id(run.judge)} at temperature 0 lists each answer's claims and checks them "
        f"against {reference(m.ids, refs)}. An answer counts when it asserts a contradicted claim "
        "or confirms the false premise and the judge rates its severity above 0.",
        f"The judge rated {unrated} more flagged answers among these variations 0, and they are "
        "not counted. The rule is meant to drop answers that only correct the user's premise, but "
        "the judge errs both ways: it also rates some answers that repeat the error 0, and counts "
        "a few that do not state it." if unrated else "",
        f"Left out, as they reproduced only with those answers counted: {', '.join(m.dropped)}."
        if m.dropped else "",
        *(f"Left out after reading the answers: {h}, as {m.theme['excluded'][h]}."
          for h in m.excluded),
        control,
        m.theme.get("control_caveat", "") if m.control else "",
        f"Target temperature {Config.temperature}, seeds {run.seeds}, languages "
        f"{', '.join(run.langs)}; harness run {run.id}.",
        f"System prompt used: {run.system}" if run.system else "No system prompt was set.",
        "Severity and breadth are self-assessed by the team against the rubric.",
        "Variations: " + ", ".join(f"{h} {pct(m.share_of(h).rate)}" for h in m.ids) + ".",
    ], 2000)


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
        "runs/<run_id>/events.jsonl logs every step of the graph; the full answers and verdicts "
        "that decide what counts are in data/llm_cache, which redteam.answers replays. Neutral "
        "control: PYTHONPATH=src python3 -m redteam.control --run <run_id>",
        f"Rebuild this file: PYTHONPATH=src python3 -m redteam.group {rebuild} --write",
    ]


def parameters(m: Measured, run: Run, control_id: str) -> dict:
    pooled = share(m.answers)
    out = {"temperature": Config.temperature, "max_output_tokens": MAX_OUTPUT_TOKENS,
           "harness_backend": run.backend, "harness_red_model": model_id(run.judge),
           "harness_run_id": run.id, "harness_langs": run.langs, "harness_seeds": run.seeds,
           "harness_reproduction_rates": rates(m.answers, run.langs),
           "harness_overall_rate": round(pooled.rate, 3),
           "harness_overall_ci95": pooled.brief()["ci95"],
           "harness_variations": [{"id": h, **m.share_of(h).brief(),
                                   "rates": rates(of(m.answers, {h}), run.langs)} for h in m.ids]}
    if m.control:
        premise, neutral = m.control
        out["harness_control"] = {"run_id": control_id, "premise": premise.brief(),
                                  "neutral": neutral.brief()}
    if m.replica:
        r = m.replica
        out["harness_replication"] = {"model": r.run.model, "run_id": r.run.id, **r.share.brief(),
                                      "variations_reproduced": r.reproduced,
                                      "variations_measured": r.measured,
                                      "variations_failed": r.failed}
    return out
