"""Every check, section by section: the recorded runs, the findings files, numbers.json, the report
and the second judge's files, each against the audit of the recorded data; and what is not
re-derived, and why. A section that cannot be checked at all is one difference, so a missing file
or key fails the run instead of shrinking it."""
from __future__ import annotations

import json
from pathlib import Path

from . import figures, prose, prose_findings, speech, table
from .agreement import rejudge_checks
from .audit import Audit
from .bounds import CI, HARNESS_DRAWS, LARGEST
from .checks import Check
from .compare import comparison_checks
from .figures import premise_rows
from .rates import DRAWS, SEED
from .runs import unlike_log
from .theme_text import text_checks
from .themes import parameter_checks

SPEECH_FINDING = "speech_dialect_hallucination"

NOT_COVERED = [
    ("technical_report.md finding 1: 'agrees in 14 of the 15' non-English answers",
     "a reading of the answers: the counting rule counts 15 of 15 there (the 15 is checked); the "
     "report leaves out one it reads as only repeating the question"),
    ("technical_report.md finding 2: 'four add details nobody gave'",
     "a reading of the answer texts, not a count the verdicts decide"),
    ("technical_report.md finding 2: 'the 8B declines in English'; finding 3: 'confirms 112'",
     "readings of the answer texts: only that no English answer, or every answer, is counted "
     "is checked, which holds as well for answers that hedge or say something else"),
    ("technical_report.md finding 3: 'one German answer adds 145', '144 (ambulance)'",
     "readings of the answer texts; only the counts of answers that state the error are checked"),
    ("technical_report.md: 65.7% yes, 15½ cantons to 6½, CHF amounts, ages and dates",
     "facts from the cited sources and the references, not from the runs"),
    ("technical_report.md use of Apertus: the commits of the served weights",
     "read from the Hugging Face API; the runs do not log them"),
    ("technical_report.md reproducibility: 2.5 s and 8-10 s",
     "timings on one machine"),
    ("technical_report.md: four strategies, six agents, four attempts, the 34% bar, 2000 draws, "
     "the 600 and 3,000 characters the log keeps",
     "design constants of the harness, used here as given; the cache keys confirm the sampling "
     "temperature and token limit of the target"),
    ("findings/*.json self_assessed_severity and its justification",
     "the team's judgement against the rubric"),
    ("findings/*.json harness_red_model, judge_model and the *_version fields",
     "the full name behind the served alias and the weight commits come from infra/ and the "
     "Hugging Face API, not from the recorded data"),
    ("findings/*.json 'counted in Standard German' after a language's rate",
     "which answers the word list reads as Standard German or Italian is taken as "
     "docs/audit/stimuli.json lists it (scripts/report_stimuli.py, redteam.lang_profile); which of "
     "them count, and whether they are most of the counted ones, is re-derived"),
    ("findings/*.json quotes in observed_behavior and the walkthroughs",
     "model output the harness picks; the picking rule is not re-derived"),
    ("findings/speech_dialect_hallucination.json meaning labels, per-clip chrF and quoted "
     "translations",
     "the audio calls are not cached and SwissDial's text is not in the repository: labels and "
     "chrF are taken as scores.json records them and only aggregated again"),
    ("the summary table's speech row title",
     "the speech finding's own headline; no data decide it"),
    ("bootstrap intervals on grids too large to enumerate (the eight-variation theme, the speech "
     "clips, the run comparisons' hypothesis resamples)",
     f"drawn again with another random stream (seed {SEED}, {DRAWS} draws) and compared within "
     f"{CI:g}, or {100 * CI:g} points where the text rounds to whole percentages: agreement, not "
     f"identity. Grids of up to {LARGEST} resamples are enumerated exactly instead, and a stated "
     f"bound agrees when {HARNESS_DRAWS} draws give it with fair chance"),
    ("docs/figures/*.svg",
     "drawn from numbers.json, whose numbers are checked"),
]


def run_checks(audit: Audit) -> list[Check]:
    checks = []
    for run in audit.runs.values():
        checks += [Check(f"data/runs/{run.id} hypotheses whose answers cannot be replayed", [],
                         run.unreplayed),
                   Check(f"data/runs/{run.id} verified answers whose replayed flag differs from "
                         "the logged one", 0, unlike_log(run))]
    return checks + [Check(f"data/runs/{audit.runs['canonical'].id}/control.json rows that cannot "
                           "be replayed", [], audit.neutral_unreplayed)]


def finding_checks(audit: Audit, findings: dict[str, dict]) -> list[Check]:
    themed = [spec["id"] for spec in audit.themes_spec]
    checks = [Check("findings/ themed files", sorted(set(findings) & set(themed)),
                    sorted(audit.themes))]
    for theme_id, theme in audit.themes.items():
        if theme_id in findings:
            checks += parameter_checks(theme_id, findings[theme_id], theme)
            checks += text_checks(theme_id, findings[theme_id], theme, audit.refs, audit.read_as)
    at = f"findings/{SPEECH_FINDING}.json"
    finding = findings[SPEECH_FINDING]
    checks += speech.parameter_checks(f"{at} model.parameters", finding["model"]["parameters"],
                                      audit.speech)
    return checks + speech.text_checks(at, finding, audit.speech)


def number_checks(audit: Audit, numbers: dict) -> list[Check]:
    canonical, at = audit.runs["canonical"], "docs/figures/numbers.json"
    return [
        Check(f"{at} canonical_run", numbers.get("canonical_run"), canonical.id),
        *figures.heatmap_checks(f"{at} gap_heatmap", numbers["gap_heatmap"], canonical),
        *figures.premise_checks(f"{at} premise_vs_neutral", numbers["premise_vs_neutral"],
                                canonical, audit.neutral, audit.themes_spec, audit.titles),
        *comparison_checks(f"{at} languages_8b_70b", numbers["languages_8b_70b"], audit.size),
        *comparison_checks(f"{at} mitigation", numbers["mitigation"], audit.mitigation),
        Check(f"{at} mitigation.system_prompt", numbers["mitigation"].get("system_prompt"),
              audit.runs["mitigation"].system),
        *speech.figure_checks(f"{at} speech_dialects", numbers["speech_dialects"], audit.speech),
        *figures.bank_checks(f"{at} bank2", numbers["bank2"], audit.runs["bank2"], audit.titles),
    ]


def report_checks(audit: Audit, report: str, findings: dict[str, dict]) -> list[Check]:
    themes = [audit.themes[spec["id"]] for spec in audit.themes_spec if spec["id"] in audit.themes]
    rows, _ = premise_rows(audit.runs["canonical"], audit.neutral, audit.themes_spec)
    headline = findings[SPEECH_FINDING]["issue_summary"]["title"]
    return [*table.table_checks(report, themes, audit.speech, headline),
            *prose.abstract(report, audit), *prose.method(report, audit),
            *prose.sizes(report, audit), *prose.captions(report, audit, len(rows)),
            *prose_findings.text_findings(report, audit), *prose_findings.speech(report, audit),
            *prose_findings.bank2(report, audit), *prose_findings.lessons(report, audit),
            *prose.closing(report, audit)]


def agreement_checks(audit: Audit, root: Path) -> list[Check]:
    checks = []
    for name, mine in audit.agreement.items():
        at = f"data/runs/{audit.runs[name].id}/rejudge.json"
        checks += rejudge_checks(at, json.loads((root / at).read_text()), mine)
    return checks


def all_checks(audit: Audit, root: Path) -> dict[str, list[Check]]:
    findings = {path.stem: json.loads(path.read_text())
                for path in sorted((root / "findings").glob("*.json"))}
    plan = {
        "recorded runs": lambda: run_checks(audit),
        "findings/*.json": lambda: finding_checks(audit, findings),
        "docs/figures/numbers.json": lambda: number_checks(
            audit, json.loads((root / "docs" / "figures" / "numbers.json").read_text())),
        "technical_report.md": lambda: report_checks(
            audit, (root / "technical_report.md").read_text(), findings),
        "second judge (rejudge.json)": lambda: agreement_checks(audit, root),
    }
    sections = {}
    for name, build in plan.items():
        try:
            sections[name] = build()
        except (OSError, LookupError, ValueError, TypeError) as e:
            sections[name] = [Check(f"{name}: the whole section", "checkable", f"failed: {e!r}")]
    return sections
