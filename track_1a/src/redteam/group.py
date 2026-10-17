"""Group a run's reproduced hypotheses into the themed findings of themes.json.

At most five findings may be submitted, so each of the four themes becomes one finding (the fifth
is redteam.speech_finding) whose variations are the theme's hypotheses that reproduced, with rates
pooled over all of their verified answers. Only answers that assert the error count
(Answer.confirmed), in the run and in the control.

    PYTHONPATH=src python3 -m redteam.group --run RUN [--control RUN] [--replication RUN] [--write]
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import clusters, paths, walkthrough
from .cache import CACHE_DIR, CacheMiss
from .graph import Config
from .run import load_hypotheses
from .scribe import ENVIRONMENT, validate
from .models import model_card
from .rubric import assess, contradicted
from .theme_finding import behaviour, overview, parameters, pct, steps
from .theme_notes import notes
from .answers import Answer, Run, load_run, neutral_answers
from .shares import Share, of, per_lang, share

FINDINGS = paths.ROOT / "findings"
THEMES = json.loads(Path(__file__).with_name("themes.json").read_text())


def subject(theme: dict, hypothesis: str) -> str | None:
    """What the hypothesis is about: the first family of the theme whose id prefix it has."""
    return next((name for prefix, name in theme["families"].items()
                 if hypothesis.startswith(prefix)), None)


def reproduced(run: Run, hypothesis: str) -> bool:
    """Reproduced by the harness, and still above its bar when only confirmed answers count."""
    return (run.outcome.get(hypothesis) == "finding"
            and share(of(run.answers, {hypothesis})).rate >= Config.min_rate)


@dataclass
class Replica:
    run: Run
    share: Share
    reproduced: list[str]
    measured: list[str]
    failed: list[str]


@dataclass
class Measured:
    theme: dict
    ids: list[str]  # reproduced variations, most reproduced first
    answers: list[Answer]  # every verified answer of those variations
    dropped: list[str]  # reproduced only while answers that correct the premise were counted
    control: tuple[Share, Share] | None  # with the false premise, neutral
    replica: Replica | None
    excluded: list[str] = field(default_factory=list)  # left out after reading, see themes.json
    neutral: list[Answer] = field(default_factory=list)  # the control's answers to these variations

    @property
    def subjects(self) -> str:
        names = list(dict.fromkeys(subject(self.theme, h) for h in self.ids))
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]

    def share_of(self, hypothesis: str) -> Share:
        return share(of(self.answers, {hypothesis}))


def measure(theme: dict, run: Run, neutral: list[Answer], replica: Run | None) -> Measured | None:
    themed = [h for h, outcome in run.outcome.items() if outcome == "finding" and subject(theme, h)]
    found = [h for h in themed if h not in theme.get("excluded", {})]
    ids = sorted((h for h in found if reproduced(run, h)),
                 key=lambda h: (-share(of(run.answers, {h})).rate, h))
    if not ids:
        return None
    answers = of(run.answers, ids)
    asked = {a.hypothesis for a in neutral} & set(ids)
    control = (share(of(answers, asked)), share(of(neutral, asked))) if asked else None
    return Measured(theme, ids, answers, [h for h in found if h not in ids], control,
                    replicate(ids, replica) if replica else None,
                    [h for h in themed if h not in found], of(neutral, asked))


def replicate(ids: list[str], run: Run) -> Replica:
    measured = [h for h in ids if run.outcome.get(h) not in (None, "error")]
    return Replica(run, share(of(run.answers, measured)),
                   [h for h in measured if reproduced(run, h)], measured,
                   [h for h in ids if run.outcome.get(h) == "error"])


def build(m: Measured, run: Run, refs: dict, control_id: str) -> dict:
    if reason := contradicted(m):
        raise ValueError(f"{m.theme['id']}: {reason}")
    desired, observed = behaviour(m, refs)
    cell = {(h, lang): s.rate for h in m.ids
            for lang, s in per_lang(of(m.answers, {h}), run.langs).items()}
    # Show only answers the judge quoted verbatim, so each one visibly states the error.
    shown = walkthrough.pick([a for a in m.answers
                              if a.confirmed and walkthrough.quotes_answer(a.evidence, a.text)],
                             lambda a: (cell[a.hypothesis, a.lang], a.severity))
    finding = {
        "schema_version": "1.0.0",
        "issue_title": m.theme["title"].format(subjects=m.subjects),
        "model": model_card(run.model, parameters(m, run, control_id)),
        "environment": ENVIRONMENT,
        "issue_summary": {
            "title": m.theme["headline"], "topic_area": m.theme["topic_area"],
            "overview": overview(m, run), "desired_behavior": desired,
            "observed_behavior": observed, **assess(m, run)},
        "apertus_response_walkthroughs": [walkthrough.render(a.prompt, a.text, run.system)
                                          for a in shown],
        "steps_to_reproduce": steps(m, run, control_id),
        "notes": notes(m, run, control_id, refs),
    }
    errors = validate(finding)
    if errors:
        raise ValueError(f"{m.theme['id']} does not match the schema: " + "; ".join(errors))
    return finding


def table(measured: list[Measured], run: Run, unthemed: list[str]) -> str:
    """Each theme with its pooled rate and clustered interval, then its variations with Wilson's."""
    def row(name: str, answers: list[Answer], *extra: str, pooled: bool = False) -> str:
        s = share(answers)
        low, high = clusters.interval(answers, run.langs) if pooled else s.ci95
        by_lang = " ".join(f"{pct(x.rate):>4s}" for x in per_lang(answers, run.langs).values())
        ci = f"{pct(low)}-{pct(high)}"
        return (f"{name:40s} {pct(s.rate):>4s} {ci:>9s}  {by_lang}"
                + "".join(f" {x:>8s}" for x in extra))

    lines = [f"{'theme (variations) / variation':40s} {'rate':>4s} {'95% CI':>9s}  "
             + " ".join(f"{lang:>4s}" for lang in run.langs) + f" {'neutral':>8s} {'replica':>8s}"]
    for m in measured:
        tried = sum(1 for h in run.outcome if subject(m.theme, h))
        neutral = pct(m.control[1].rate) if m.control else "-"
        replica = pct(m.replica.share.rate) if m.replica and m.replica.share.n else "-"
        lines.append(row(f"{m.theme['id']} ({len(m.ids)}/{tried})", m.answers, neutral, replica,
                         pooled=True))
        lines += [row("  " + h, of(m.answers, {h})) for h in m.ids]
    if unthemed:
        lines.append("reproduced, in no theme:")
        lines += [row("  " + h, of(run.answers, {h})) for h in unthemed]
    return "\n".join(lines)


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", required=True, help="run whose findings are grouped")
    ap.add_argument("--control", help="run whose control.json to use (default: --run)")
    ap.add_argument("--replication", help="run of the same hypotheses on another target model")
    ap.add_argument("--write", action="store_true", help="write findings/<theme>.json")
    ap.add_argument("--themes", nargs="*",
                    help="only these theme ids (each theme from the run that measured it)")
    args = ap.parse_args(argv)
    for run_id in filter(None, (args.run, args.control, args.replication)):
        if paths.run_dir(run_id) is None:
            ap.error(f"no run {run_id} in {paths.RUNS} or {paths.SHIPPED}")
    control_id = args.control or args.run
    control_path = paths.run_dir(control_id) / "control.json"
    if args.control and not control_path.exists():
        ap.error(f"{control_path} does not exist")
    refs = {h["id"]: h for h in load_hypotheses()}

    def load(run_id: str) -> Run:
        return load_run(paths.run_dir(run_id), refs, CACHE_DIR)

    try:
        run = load(args.run)
        rows = json.loads(control_path.read_text()) if control_path.exists() else []
        control_run = run if control_id == run.id else load(control_id)
        neutral = neutral_answers(rows, refs, control_run, CACHE_DIR)
        replica = load(args.replication) if args.replication else None
    except CacheMiss as e:
        ap.error(f"{e}; answers and verdicts are replayed from {CACHE_DIR}")
    if args.write and run.backend != "vllm":
        ap.error(f"refusing --write: a {run.backend} run is not a new measurement of Apertus")
    themes = [t for t in THEMES if not args.themes or t["id"] in args.themes]
    measured = [m for m in (measure(t, run, neutral, replica) for t in themes) if m]
    unthemed = [h for h in run.outcome
                if reproduced(run, h) and not any(subject(t, h) for t in THEMES)]
    print(table(measured, run, unthemed))
    findings = {m.theme["id"]: build(m, run, refs, control_id) for m in measured}
    if args.write:
        for theme_id, finding in findings.items():
            path = FINDINGS / f"{theme_id}.json"
            path.write_text(json.dumps(finding, indent=2, ensure_ascii=False) + "\n")
            print(f"wrote {path}")
    return findings


if __name__ == "__main__":
    main()
