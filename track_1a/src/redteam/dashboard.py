"""What the dashboard shows of a run: its events with the verifier results counted like the
findings, its findings, the neutral control, the second judge's agreement and the hypotheses,
plus the five submitted findings, how each audit in docs/audit/ came out, where the run's files
are and what a new run would use (next_run.py). Also the list of runs for the picker.

The server asks for this every few hundred milliseconds while a run is live, so the hypothesis
banks, the submitted findings, the audits and the recounts are kept until the files they come
from change.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from contextlib import suppress
from pathlib import Path

from . import answers, next_run, paths, review, stats
from . import run as run_mod
from .cache import CACHE_DIR
from .events import first_event, read_events
from .graph import Config

HYPOTHESIS_FIELDS = ("title", "domain", "hypothesis", "reference", "harm", "sources")
FINDINGS = paths.ROOT / "findings"
AUDIT = paths.ROOT / "docs" / "audit"
CANONICAL_RUN = "20261016-172309-1f71"

# The four runs the report cites, by the name the report gives them. Every other run is listed by
# its date and target model.
REPORT_RUNS = {
    CANONICAL_RUN: "Apertus 8B",
    "20261017-140533-a21a": "Apertus 70B",
    "20261017-144423-5519": "Apertus 70B with a safety system prompt",
    "20261017-143329-b04d": "Apertus 70B, second question bank",
}

# A run without its end event is still going only if it wrote to its log lately: a run that was
# killed never writes one, and must not stay the page's default run for good.
LIVE_WINDOW_S = 600


def _json_file(path: Path, default):
    # Files of a live run can be caught half-written; treat them as not there yet.
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# kind -> (key, value), computed again when the key changes. One entry per kind is enough: the
# dashboard shows one run at a time. The picker's counts of the report runs have a kind per run.
_memo: dict[str, tuple] = {}


def _memoised(kind: str, key: tuple, compute):
    held = _memo.get(kind)
    if held is None or held[0] != key:
        held = _memo[kind] = (key, compute())
    return held[1]


def _files_key(files) -> tuple:
    return tuple((f.name, f.stat().st_mtime_ns) for f in sorted(files))


def bank() -> dict[str, dict]:
    """Every hypothesis by id, read again only when a bank file changes."""
    key = _files_key(run_mod.HYPOTHESES.glob("*.json"))
    return _memoised("bank", key, lambda: {h["id"]: h for h in run_mod.load_hypotheses()})


def hypotheses() -> dict:
    return {i: {k: h.get(k) for k in HYPOTHESIS_FIELDS} for i, h in bank().items()}


def state(run_id: str) -> dict:
    """The run ("latest" for the newest local one); run_id is None when there is no such run."""
    d = paths.run_dir(run_id)
    shared = {"run_id": d.name if d else None, "run_folder": _folder(d) if d else None,
              "min_rate": Config.min_rate, "hypotheses": hypotheses(),
              "submitted": _submitted(), "checks": _checks(), "human_labels": _human_labels(),
              "next_run": next_run.plan()}
    if d is None:
        return {**shared, "events": [], "findings": [], "uncounted": [], "control": [],
                "rejudge": None, "language_means": {}}
    events = read_events(d / "events.jsonl")
    verified, uncounted = _recount(d, events)
    below = _below_bar(verified)
    return {**shared, "events": events, "findings": _findings(d, events, below),
            "uncounted": sorted(uncounted), "control": _recount_control(d),
            "rejudge": _agreement(d), "language_means": _language_means(d, verified)}


def _agreement(run_dir: Path) -> dict | None:
    r = _json_file(run_dir / "rejudge.json", None)
    return {k: r.get(k) for k in ("n", "kappa", "raw_agreement")} if r else None


def _folder(run_dir: Path) -> str:
    """Where the run is, as a reader of the repository finds it: runs/<id> or data/runs/<id>."""
    try:
        return run_dir.relative_to(paths.ROOT).as_posix()
    except ValueError:  # run folders moved elsewhere, as in the tests
        return run_dir.as_posix()


def _submitted() -> list[dict]:
    """The submitted findings (findings/*.json), trimmed to what the dashboard shows of them; read
    again only when one of the files changes."""
    files = sorted(FINDINGS.glob("*.json"))
    return _memoised("submitted", _files_key(files),
                     lambda: [_trim(f.name, d) for f in files
                              if isinstance(d := _json_file(f, None), dict)])


def _trim(name: str, f: dict) -> dict:
    model, summary = f.get("model") or {}, f.get("issue_summary") or {}
    p = model.get("parameters") or {}
    return {"file": name, "issue_title": f.get("issue_title"), "model": model.get("name"),
            "model_version": model.get("version"), "run_id": p.get("harness_run_id"),
            "severity": summary.get("self_assessed_severity"),
            "breadth": summary.get("self_assessed_breadth"), "overview": summary.get("overview"),
            "variations": p.get("harness_variations"),
            "overall_rate": p.get("harness_overall_rate"),
            "overall_ci95": p.get("harness_overall_ci95"), "control": p.get("harness_control"),
            "replication": p.get("harness_replication"), "reproduce": f.get("steps_to_reproduce"),
            # Only the speech finding has it: per dialect, the share of unrelated transcripts.
            "unrelated": _with_cluster_ci(p.get("unrelated"), p.get("unrelated_cluster_ci95"))}


def _with_cluster_ci(unrelated: dict | None, clustered: dict | None) -> dict | None:
    """The speech totals carry the interval over speakers and sentences next to their counts; the
    clips are not independent, so the card shows no other interval for them."""
    if not unrelated or not clustered or "all" not in unrelated:
        return unrelated
    totals = {model: {**counts, "cluster_ci95": clustered.get(model)}
              for model, counts in unrelated["all"].items()}
    return {**unrelated, "all": totals}


def _checks() -> list[dict]:
    """How each audit and the second judge came out, in the overview's order, with the files they
    come from; read again only when one of those files changes. An audit that is missing, or
    written in another shape, drops out of the list rather than taking the page down."""
    def read():
        checks = []
        for check in (_crosscheck, _judges, _scorer, _stats, _prompts, _references):
            with suppress(KeyError, TypeError, AttributeError):
                checks.append(check())
        return [c for c in checks if c]
    files = [*AUDIT.glob("*.json"), *paths.SHIPPED.glob("*/rejudge.json")]
    return _memoised("checks", _files_key(files), read)


def _crosscheck() -> dict:
    cc = _json_file(AUDIT / "crosscheck.json", {})
    return {"check": "recount", "file": "docs/audit/crosscheck.json", "checked": cc["checked"],
            "differ": cc["differ"]}


def _judges() -> dict | None:
    # The recorded copies, so that every clone shows the same agreement.
    runs = [{"run": name, **a} for run_id, name in REPORT_RUNS.items()
            if (a := _agreement(paths.SHIPPED / run_id)) and a["kappa"] is not None]
    return {"check": "judge", "file": "data/runs/*/rejudge.json", "runs": runs} if runs else None


def _scorer() -> dict:
    run = _json_file(AUDIT / "scorer.json", {})["runs"][CANONICAL_RUN]
    labels = run["agreement"]["by_label"]
    return {"check": "scorer", "file": "docs/audit/scorer.json", "model": run["model"],
            "scorable": len(run["scorable_hypotheses"]), "hypotheses": run["hypotheses"],
            "false_only": labels["false_only"], "true_only": labels["true_only"]}


def _stats() -> dict:
    s = _json_file(AUDIT / "stats.json", {})
    # Romansh against English counted over hypotheses, which needs no independence of answers.
    runs = [{"model": s["models"][run], **data["english_vs"]["rm"]["sign"]}
            for run, data in s["runs"].items()]
    return {"check": "stats", "file": "docs/audit/stats.json", "romansh_vs_english": runs}


def _prompts() -> dict:
    total = _json_file(AUDIT / "stimuli.json", {})["prompts_total"]
    return {"check": "prompts", "file": "docs/audit/stimuli.json", "prompts": total["prompts"],
            "word_list": total["word_list"], "uncertain": total["uncertain"]}


def _references() -> dict | None:
    files = sorted(AUDIT.glob("references-*.json"))
    hyps = [h for f in files for h in _json_file(f, {})["hypotheses"]]
    if not hyps:
        return None
    sources = [s for h in hyps for s in h["sources"]]
    return {"check": "references", "file": "docs/audit/references-*.json", "hypotheses": len(hyps),
            "verdicts": dict(Counter(h["verdict"] for h in hyps)), "sources": len(sources),
            "unreachable": sum(s["status"] == "unreachable" for s in sources),
            "uncited": sum(any(s.get("cited") is False for s in h["sources"]) for h in hyps)}


def _human_labels() -> int:
    """How many judge verdicts a person has checked on the review page."""
    path = review.LABELS
    key = (str(path), path.stat().st_mtime_ns if path.exists() else None)
    return _memoised("labels", key, lambda: review.agreement()["n"])


def _findings(run_dir: Path, events: list[dict], below: set[str]) -> list[dict]:
    """The findings files of the hypotheses the run wrote up, each named after its hypothesis (a
    file's title may be a sentence), minus those the recount puts below the bar. The copies of the
    recorded runs in data/runs/ leave the files out, so a written-up hypothesis without one is
    listed by its id alone and the dashboard builds its card from the events."""
    files = {p.stem: p for p in run_dir.glob("findings/*.json")}
    written = {e["hypothesis"] for e in events if e["node"] == "scribe" and e["status"] == "done"}
    return [{**(_json_file(files[h], {}) if h in files else {}), "hypothesis": h}
            for h in sorted((written | set(files)) - below)]


def _verified(events: list[dict]) -> dict[str, dict]:
    return {e["hypothesis"]: e["data"] for e in events
            if e["node"] == "verifier" and e["status"] == "done"}


def _below_bar(verified: dict[str, dict]) -> set[str]:
    return {h for h, v in verified.items() if v["overall"] < Config.min_rate}


def _recount(run_dir: Path, events: list[dict]) -> tuple[dict[str, dict], set[str]]:
    """Verifier results by hypothesis, counted like the findings, and the hypotheses that could
    not be counted (see _counted). Counted again only when another hypothesis has been verified."""
    verified = _verified(events)
    counted, uncounted = _memoised("recount", (str(run_dir), len(verified)),
                                   lambda: _counted(run_dir, verified))
    for h, data in counted.items():
        verified[h].update(data)
    return verified, uncounted


def _counted(run_dir: Path, verified: dict[str, dict]) -> tuple[dict[str, dict], set[str]]:
    """Verifier results counted like the findings (answers.Answer.confirmed), and the hypotheses
    that could not be counted, which keep the share the judge flagged. Runs log the counted
    results themselves since the counting rule; older runs are replayed from the LLM cache, which
    is not free.

    Each result also keeps, as flagged, how many answers per language the judge flagged before the
    recount, so the dashboard can show both numbers. Runs that log their counted results logged
    the flags in per_lang."""
    # Read before answers.recount rewrites per_lang in place.
    flagged = {h: {"flagged": {lang: cell["k"] for lang, cell in data["per_lang"].items()}}
               for h, data in verified.items() if data.get("per_lang")}
    older = {h: data for h, data in verified.items() if "counted" not in data}
    uncounted = answers.recount(run_dir, older, bank(), CACHE_DIR)
    return {h: {**data, **data.get("counted", {}), **flagged.get(h, {})}
            for h, data in verified.items()}, uncounted


def _recount_control(run_dir: Path) -> list[dict]:
    """The neutral control counted the same way; rows the cache cannot replay keep their logged
    rates and have no counts. Replayed again only when control.json changes."""
    path = run_dir / "control.json"
    rows = _json_file(path, [])
    if not rows:
        return []
    key = (str(path), path.stat().st_mtime_ns, len(rows))
    shares = _memoised("control", key,
                       lambda: answers.control_shares(run_dir, rows, bank(), CACHE_DIR))
    for row in rows:
        if row["id"] in shares:
            premise, neutral = shares[row["id"]]
            row["premise_rate"], row["premise_k"], row["premise_n"] = premise.rate, premise.k, premise.n
            row["neutral_rate"], row["neutral_ci95"] = neutral.rate, list(neutral.ci95)
            row["neutral_k"], row["neutral_n"] = neutral.k, neutral.n
    return rows


def _language_means(run_dir: Path, verified: dict[str, dict]) -> dict[str, dict]:
    """Per language, the mean failure rate over the verified hypotheses (the heatmap's average
    row) with a 95% interval that resamples hypotheses, since the answers to one hypothesis are not
    independent; k and n add up the answers. Computed again when another hypothesis is verified."""
    def compute():
        cells: dict[str, dict[str, dict]] = {}
        for h, data in verified.items():
            for lang, cell in (data.get("per_lang") or {}).items():
                cells.setdefault(lang, {})[h] = cell
        means = {}
        for lang, by_hyp in cells.items():
            rates = {(h, lang): cell["rate"] for h, cell in by_hyp.items()}
            means[lang] = {"k": sum(c["k"] for c in by_hyp.values()),
                           "n": sum(c["n"] for c in by_hyp.values()),
                           "rate": sum(rates.values()) / len(rates),
                           "ci95": list(stats.cluster_bootstrap(rates))}
        return means
    return _memoised("means", (str(run_dir), len(verified)), compute)


def runs() -> list[dict]:
    """Every run newest first, with the number of findings files the harness wrote for it, the
    report's name for it, whether it set a system prompt, whether it is the one "latest" names and
    whether it is still going."""
    rows, newest = [], paths.latest()
    for d in reversed(paths.run_dirs()):
        if d.name.startswith("_"):  # aborted or archived by hand
            continue
        start = first_event(d / "events.jsonl")
        data = start.get("data") or {}
        rows.append({"id": d.name, "label": data.get("label") or "",
                     "model": start.get("model"), "backend": start.get("backend"),
                     "written": len(list(d.glob("findings/*.json"))),
                     "name": REPORT_RUNS.get(d.name, ""), "report": d.name in REPORT_RUNS,
                     "system": bool(data.get("system")), "latest": d.name == newest,
                     "live": d.name == newest and _going(d / "events.jsonl"),
                     "reproduced": _reproduced(d) if d.name in REPORT_RUNS else None})
    return rows


def _reproduced(run_dir: Path) -> int:
    """How many findings state() lists for a run, counted again only when its log changes. The
    picker labels each report run with it before the reader opens any; each run has its own memo
    entry so that the run on screen keeps its recount."""
    log = run_dir / "events.jsonl"

    def count():
        events = read_events(log)
        counted, _ = _counted(run_dir, _verified(events))
        return len(_findings(run_dir, events, _below_bar(counted)))
    return _memoised("reproduced " + run_dir.name, (str(run_dir), log.stat().st_mtime_ns), count)


def _going(log: Path) -> bool:
    if time.time() - log.stat().st_mtime > LIVE_WINDOW_S:
        return False
    return not any(e["node"] == "graph" and e["status"] == "end" for e in read_events(log))
