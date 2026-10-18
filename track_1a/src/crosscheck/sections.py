"""Every check, section by section: the findings files, numbers.json and the report, each against
the audit of the recorded data. A section that cannot be checked at all is one difference, so a
missing file or key fails the run instead of shrinking it."""
from __future__ import annotations

import json
from pathlib import Path

from . import figures, prose, prose_findings, speech, table
from .agreement import rejudge_checks
from .audit import RUNS, Audit
from .checks import Check
from .compare import comparison_checks
from .figures import premise_rows
from .runs import unlike_log
from .theme_checks import parameter_checks
from .theme_text import text_checks

SPEECH_FINDING = "speech_dialect_hallucination"


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
            checks += text_checks(theme_id, findings[theme_id], theme, audit.refs)
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


def agreement_checks(audit: Audit, shipped: Path) -> list[Check]:
    checks = []
    for name, mine in audit.agreement.items():
        run_id = RUNS[name]
        stated = json.loads((shipped / run_id / "rejudge.json").read_text())
        checks += rejudge_checks(f"data/runs/{run_id}/rejudge.json", stated, mine)
    return checks


def all_checks(audit: Audit, root: Path) -> list[Check]:
    findings = {path.stem: json.loads(path.read_text())
                for path in sorted((root / "findings").glob("*.json"))}
    plan = {
        "recorded runs": lambda: run_checks(audit),
        "findings": lambda: finding_checks(audit, findings),
        "numbers.json": lambda: number_checks(
            audit, json.loads((root / "docs" / "figures" / "numbers.json").read_text())),
        "technical_report.md": lambda: report_checks(
            audit, (root / "technical_report.md").read_text(), findings),
        "rejudge.json": lambda: agreement_checks(audit, root / "data" / "runs"),
    }
    checks = []
    for name, build in plan.items():
        try:
            checks += build()
        except (OSError, LookupError, ValueError, TypeError) as e:
            checks.append(Check(f"{name}: the whole section", "checkable", f"failed: {e!r}"))
    return checks
