"""Recorded runs and speech runs for the report tests, written as the harness leaves them, and a
test case that fixes the themes and empties the LLM cache."""
import io
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src")]

import helpers  # noqa: E402
import report_figures as figures  # noqa: E402
import report_runs as runs  # noqa: E402
from redteam.stats import wilson  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
LANGS = ["en", "de", "fr"]
SEEDS = 3
JUDGE = "apertus-70b-fp8"
# Fixed, so editing themes.json never changes these tests.
THEMES = [{"families": {"vote_": "voting rules"},
           "excluded": {"vote_postal_deadline": "its prompts name no country"}},
          {"families": {"privacy_": "personal data"},
           "control_caveat": "The neutral question named no one."}]
VERDICTS = {"u": "unrelated", "p": "partial", "s": "same"}


def quietly(call, *args):
    """Call with the progress it prints and the notes it writes to stderr caught; the result and
    the notes."""
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as notes:
        return call(*args), notes.getvalue()


def per_lang(ks):
    return {lang: {"rate": k / SEEDS, "k": k, "n": SEEDS, "ci95": list(wilson(k, SEEDS))}
            for lang, k in zip(LANGS, ks)}


def write_logged_run(root, run_id, model, verified, findings=(), unbroken=(), failed=(),
                     system=None, control=None, reworded=(), finished=True):
    """A run whose answers are not in the LLM cache, so the figures count the judge's logged flags.
    It holds only the events the figures read; verified maps id -> wrong answers per language.
    Hypotheses in reworded were attacked with prompts that differ from the other runs'."""
    def event(hyp, node, status, data):
        return {"t": 0, "run_id": run_id, "hypothesis": hyp, "node": node, "status": status,
                "backend": "vllm", "model": model, "data": data}

    attacked = [*verified, *unbroken, *failed]
    events = [event(None, "graph", "start", {"hypotheses": attacked, "langs": LANGS, "label": "",
                                             "system": system, "red_model": JUDGE})]
    for hyp, ks in verified.items():
        k, n = sum(ks), SEEDS * len(ks)
        prompts = {lang: f"{hyp} {lang}" + (" again" if hyp in reworded else "") for lang in LANGS}
        events += [event(hyp, "mutator", "done", {"prompts": prompts}),
                   event(hyp, "verifier", "start", {"seeds": list(range(SEEDS)), "langs": LANGS}),
                   event(hyp, "verifier", "done", {"per_lang": per_lang(ks), "overall": k / n,
                                                   "overall_ci95": list(wilson(k, n))})]
    events += [event(h, "scribe", "done", {}) for h in findings]
    events += [event(h, "graph", "no_issue", {"attempts": 4}) for h in unbroken]
    events += [event(h, "graph", "error", {"error": "JSONDecodeError"}) for h in failed]
    run_dir = Path(root) / run_id
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if finished:
        (run_dir / "summary.json").write_text("{}")
    if control:
        (run_dir / "control.json").write_text(json.dumps(control))
    return run_dir


def finish_verification(run_dir):
    """Log each verifier result and end the run, as the graph does and helpers.write_run leaves
    out: per language, the answers the judge flagged."""
    events = events_of(run_dir)
    flags = {}
    for e in events:
        if (e["node"], e["status"]) == ("verifier", "progress"):
            flags.setdefault(e["hypothesis"], {}).setdefault(e["data"]["lang"], []).append(
                e["data"]["violation"])
    done = []
    for hyp, by_lang in flags.items():
        cells = {lang: {"k": sum(f), "n": len(f), "rate": sum(f) / len(f),
                        "ci95": list(wilson(sum(f), len(f)))} for lang, f in by_lang.items()}
        k, n = sum(c["k"] for c in cells.values()), sum(c["n"] for c in cells.values())
        done.append(helpers.event(run_dir.name, "vllm", hyp, "verifier", "done", per_lang=cells,
                                  overall=k / n, overall_ci95=list(wilson(k, n))))
    with (run_dir / "events.jsonl").open("a") as f:
        f.writelines(json.dumps(e) + "\n" for e in done)
    (run_dir / "summary.json").write_text("{}")


def events_of(run_dir):
    return [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]


SPEECH = {"model": "onprem-ai/Apertus-v1.5-70B-FP8", "judge": JUDGE,
          "whisper_model": "gcoli/whisper-large-v3-swiss-german-mit"}


def clips(grid):
    """Judged clips from a map of dialect to one verdict letter per sentence."""
    return [{"dialect": d, "sentence_id": i, "chrf": 30.0, "meaning": VERDICTS[v]}
            for d, letters in grid.items() for i, v in enumerate(letters)]


def write_speech(folder, apertus, whisper):
    """A speech run folder as speech_eval and speech_compare leave it."""
    folder.mkdir(parents=True)
    (folder / "results.json").write_text(json.dumps(
        {"model": SPEECH["model"], "judge": JUDGE, "clips": clips(apertus)}))
    (folder / "whisper_compare.json").write_text(json.dumps(
        {"whisper_model": SPEECH["whisper_model"], "whisper_clips": clips(whisper)}))
    return folder


def write_scores(folder, apertus, whisper):
    """A speech run folder as data/runs/speech/ ships it: per-clip verdicts only."""
    folder.mkdir(parents=True)
    (folder / "scores.json").write_text(json.dumps(
        {"run_id": folder.name, **SPEECH, "apertus": clips(apertus), "whisper": clips(whisper)}))
    return folder


def texts(svg):
    return [t.text for t in ET.fromstring(svg).iter(f"{SVG}text")]


def control_row(hyp, premise, neutral):
    answers = {lang: ["an answer"] * SEEDS for lang in LANGS}
    n = SEEDS * len(LANGS)
    return {"id": hyp, "premise_rate": premise, "neutral_rate": neutral,
            "neutral_ci95": list(wilson(round(neutral * n), n)), "neutral_answers": answers}


class Isolated(unittest.TestCase):
    """A temporary folder, an empty LLM cache and fixed themes for each test."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for target, name, value in ((runs, "CACHE", self.root / "no-cache"),
                                    (figures, "THEMES", THEMES)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
