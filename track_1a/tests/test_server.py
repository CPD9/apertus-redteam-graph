import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import answers, server  # noqa: E402
from test_group import GRID, LANGS, event, write_control, write_run  # noqa: E402

RUN = "20261016-172309-1f71"
HYP = {"id": "vote_initiative_signatures", "topic_area": "Misrepresentation", "domain": "voting",
       "hypothesis": "h", "reference": "100,000 signatures in 18 months", "harm": "x", "sources": []}
START = {"node": "graph", "status": "start", "backend": "vllm", "model": "swiss-ai/Apertus-v1.5-8B",
         "data": {"hypotheses": [HYP["id"]], "label": "8B target"}}


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


class StateTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs = Path(d.name)
        for patcher in (mock.patch.object(server, "RUNS", self.runs),
                        mock.patch.object(server, "CACHE", self.runs / "cache"),
                        mock.patch.dict(server._counted, clear=True),
                        mock.patch.dict(server._neutral, clear=True),
                        mock.patch.object(server.run_mod, "load_hypotheses", return_value=[HYP])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_run(self, run_id: str, events: str) -> Path:
        run = self.runs / run_id
        run.mkdir()
        (run / "events.jsonl").write_text(events)
        return run

    def test_latest_run_carries_control_rejudge_and_hypotheses(self):
        # The second line is cut off mid-write, as when a live run is read.
        run = self.make_run(RUN, json.dumps(START) + '\n{"node": "verif')
        write_json(run / "findings" / f"{HYP['id']}.json", {"issue_summary": {"title": HYP["id"]}})
        write_json(run / "control.json", [{"id": HYP["id"], "neutral_rate": 0.5}])
        write_json(run / "rejudge.json", {"n": 2, "kappa": 1.0, "raw_agreement": 1.0, "cells": [{}, {}]})
        (self.runs / "latest").write_text(RUN + "\n")

        s = server.state("latest")
        self.assertEqual(s["run_id"], RUN)
        self.assertEqual(len(s["events"]), 1)
        self.assertEqual(len(s["findings"]), 1)
        self.assertEqual(s["control"], [{"id": HYP["id"], "neutral_rate": 0.5}])
        self.assertEqual(s["rejudge"], {"n": 2, "kappa": 1.0, "raw_agreement": 1.0})
        self.assertEqual(s["hypotheses"], {HYP["id"]: {"domain": "voting", "hypothesis": "h",
                                                       "reference": HYP["reference"], "harm": "x",
                                                       "sources": []}})

    def test_run_without_control_or_rejudge(self):
        self.make_run(RUN, json.dumps(START) + "\n")
        s = server.state(RUN)
        self.assertEqual((s["control"], s["rejudge"], s["findings"]), ([], None, []))

    def test_runs_that_logged_only_rates_keep_them(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.5, "de": 1.0}, "overall": 0.75}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        self.assertEqual(server.state(RUN)["events"][1]["data"], done["data"])

    def test_unknown_or_unsafe_run_ids_resolve_to_nothing(self):
        self.make_run(RUN, "")
        for run_id in ("latest", "nope", "..", "../" + RUN, ""):
            s = server.state(run_id)
            self.assertIsNone(s["run_id"], run_id)
            self.assertEqual(s["events"], [])

    def test_runs_are_newest_first_with_labels(self):
        self.make_run("20261016-100000-aaaa", json.dumps({**START, "data": {}}) + "\n")
        self.make_run("20261017-100000-bbbb", json.dumps(START) + "\n")
        self.make_run("_aborted_20261017-110000-cccc", json.dumps(START) + "\n")
        (self.runs / "speech").mkdir()
        rows = server.runs()
        self.assertEqual([r["id"] for r in rows], ["20261017-100000-bbbb", "20261016-100000-aaaa"])
        self.assertEqual([r["label"] for r in rows], ["8B target", ""])
        self.assertEqual(rows[0]["model"], "swiss-ai/Apertus-v1.5-8B")
        self.assertEqual(rows[0]["flagged"], 0)


class RecountTest(unittest.TestCase):
    """A run and its control replayed from the LLM cache, built as in test_group."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, cache = Path(d.name) / "runs", Path(d.name) / "cache"
        for patcher in (mock.patch.object(server, "RUNS", self.runs),
                        mock.patch.object(server, "CACHE", cache),
                        mock.patch.dict(server._counted, clear=True),
                        mock.patch.dict(server._neutral, clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        write_run(self.runs, cache, RUN)
        write_control(self.runs, cache, RUN)
        self.log_rates(self.runs / RUN)

    @staticmethod
    def log_rates(run: Path):
        """Logged numbers that the recount has to replace: every answer counted as a failure."""
        every = {lang: {"k": 3, "n": 3, "rate": 1.0, "ci95": [0.44, 1.0]} for lang in LANGS}
        with (run / "events.jsonl").open("a") as f:
            for h in GRID:
                done = event(RUN, "vllm", h, "verifier", "done", per_lang=every, overall=1.0,
                             overall_ci95=[0.82, 1.0])
                f.write(json.dumps(done) + "\n")
        rows = json.loads((run / "control.json").read_text())
        for row in rows:
            row.update(neutral_rate=1.0, neutral_ci95=[0.82, 1.0], premise_rate=1.0)
        (run / "control.json").write_text(json.dumps(rows))

    def verified(self, s: dict) -> dict:
        return {e["hypothesis"]: e["data"] for e in s["events"]
                if e["node"] == "verifier" and e["status"] == "done"}

    def test_verifier_results_count_confirmed_answers_with_their_intervals(self):
        s = server.state(RUN)
        deadline = self.verified(s)["vote_postal_deadline"]  # en rrr, de wwr, fr wwr
        self.assertAlmostEqual(deadline["overall"], 4 / 9)
        self.assertEqual(deadline["per_lang"]["en"]["k"], 0)
        self.assertEqual(deadline["per_lang"]["en"]["ci95"], list(answers.Share(0, 3).ci95))
        self.assertAlmostEqual(self.verified(s)["vote_postal_signature"]["overall"], 1 / 9)

    def test_control_counts_neutral_answers_alike_and_takes_the_premise_from_the_run(self):
        control = {row["id"]: row for row in server.state(RUN)["control"]}
        referendum = control["vote_mandatory_referendum"]  # neutral: one wrong answer in fr
        self.assertAlmostEqual(referendum["neutral_rate"], 1 / 9)
        self.assertEqual(referendum["neutral_ci95"], list(answers.Share(1, 9).ci95))
        self.assertEqual(referendum["premise_rate"], 1.0)
        self.assertEqual(control["vote_postal_deadline"]["neutral_rate"], 0.0)
        self.assertAlmostEqual(control["vote_postal_deadline"]["premise_rate"], 4 / 9)

    def test_control_keeps_the_logged_rates_when_the_cache_cannot_replay_it(self):
        with mock.patch.object(server, "CACHE", self.runs / "no-cache"):
            row = server.state(RUN)["control"][0]
        self.assertEqual((row["neutral_rate"], row["neutral_ci95"], row["premise_rate"]),
                         (1.0, [0.82, 1.0], 1.0))

    def test_control_is_replayed_once_per_control_file(self):
        with mock.patch.object(server.answers, "neutral_answers",
                               wraps=answers.neutral_answers) as replay:
            first, second = server.state(RUN)["control"], server.state(RUN)["control"]
        self.assertEqual(replay.call_count, 1)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
