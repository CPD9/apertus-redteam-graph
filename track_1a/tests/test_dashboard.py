"""The dashboard's view of a run: events, findings, control and second judge, counted from the
LLM cache like the findings (redteam.dashboard)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import (GRID, HYP, LANGS, RUN, START, event, patch, use_runs,  # noqa: E402
                     write_control, write_json, write_run)
from redteam import answers, dashboard  # noqa: E402
from redteam.shares import Share  # noqa: E402


class StateTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs = Path(d.name)
        use_runs(self, self.runs)
        self.load = mock.Mock(return_value=[HYP])
        patch(self, mock.patch.object(dashboard, "CACHE_DIR", self.runs / "cache"),
              mock.patch.dict(dashboard._memo, clear=True),
              mock.patch.object(dashboard.run_mod, "load_hypotheses", self.load))

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

        s = dashboard.state("latest")
        self.assertEqual(s["run_id"], RUN)
        self.assertEqual(len(s["events"]), 1)
        self.assertEqual(len(s["findings"]), 1)
        self.assertEqual(s["control"], [{"id": HYP["id"], "neutral_rate": 0.5}])
        self.assertEqual(s["rejudge"], {"n": 2, "kappa": 1.0, "raw_agreement": 1.0})
        self.assertEqual(s["hypotheses"], {HYP["id"]: {"title": "Initiative signatures",
                                                       "domain": "voting", "hypothesis": "h",
                                                       "reference": HYP["reference"], "harm": "x",
                                                       "sources": []}})

    def test_findings_are_named_by_their_file_whatever_their_title(self):
        run = self.make_run(RUN, json.dumps(START) + "\n")
        title = "Apertus confirms a wrong signature count"
        write_json(run / "findings" / f"{HYP['id']}.json", {"issue_summary": {"title": title}})
        finding, = dashboard.state(RUN)["findings"]
        self.assertEqual((finding["hypothesis"], finding["issue_summary"]["title"]), (HYP["id"], title))

    def test_findings_below_the_bar_are_left_out_whatever_their_title(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.0, "de": 0.5}, "overall": 0.25}}
        run = self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        write_json(run / "findings" / f"{HYP['id']}.json", {"issue_summary": {"title": "a sentence"}})
        self.assertEqual(dashboard.state(RUN)["findings"], [])

    def test_shipped_copies_list_written_up_hypotheses_without_their_files(self):
        shipped = self.runs / "data-runs"
        use_runs(self, self.runs, shipped)
        kept, dropped = HYP["id"], "vote_postal_deadline"
        events = [START] + [
            {"node": "verifier", "status": "done", "hypothesis": h, "data": {"overall": rate}}
            for h, rate in ((kept, 0.5), (dropped, 0.2))] + [
            {"node": "scribe", "status": "done", "hypothesis": h, "data": {}} for h in (kept, dropped)]
        (shipped / RUN).mkdir(parents=True)
        (shipped / RUN / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        self.assertEqual(dashboard.state(RUN)["findings"], [{"hypothesis": kept}])

    def test_runs_that_log_their_counted_results_are_not_replayed(self):
        flagged = {"per_lang": {"en": {"k": 2, "n": 2, "rate": 1.0, "ci95": [0.34, 1.0]}},
                   "rates": {"en": 1.0}, "overall": 1.0, "overall_ci95": [0.34, 1.0]}
        counted = {"per_lang": {"en": {"k": 1, "n": 2, "rate": 0.5, "ci95": [0.09, 0.91]}},
                   "rates": {"en": 0.5}, "overall": 0.5, "overall_ci95": [0.09, 0.91]}
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {**flagged, "counted": counted}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        with mock.patch.object(dashboard.answers, "load_run") as load_run:
            s = dashboard.state(RUN)
        self.assertFalse(load_run.called)
        self.assertEqual({k: s["events"][1]["data"][k] for k in counted}, counted)
        self.assertEqual(s["uncounted"], [])

    def test_run_without_control_or_rejudge(self):
        self.make_run(RUN, json.dumps(START) + "\n")
        s = dashboard.state(RUN)
        self.assertEqual((s["control"], s["rejudge"], s["findings"], s["uncounted"]), ([], None, [], []))

    def test_runs_that_logged_only_rates_keep_them_and_are_marked_uncounted(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.5, "de": 1.0}, "overall": 0.75}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        s = dashboard.state(RUN)
        self.assertEqual(s["events"][1]["data"], done["data"])
        self.assertEqual(s["uncounted"], [HYP["id"]])

    def test_unknown_or_unsafe_run_ids_resolve_to_nothing(self):
        self.make_run(RUN, "")
        for run_id in ("latest", "nope", "..", "../" + RUN, ""):
            s = dashboard.state(run_id)
            self.assertIsNone(s["run_id"], run_id)
            self.assertEqual((s["events"], s["uncounted"]), ([], []))

    def test_banks_are_read_again_only_when_a_bank_file_changes(self):
        done = {"node": "verifier", "status": "done", "hypothesis": HYP["id"],
                "data": {"rates": {"en": 0.5}, "overall": 0.5}}
        self.make_run(RUN, json.dumps(START) + "\n" + json.dumps(done) + "\n")
        banks = self.runs / "hypotheses"
        write_json(banks / "bank.json", [HYP])
        with mock.patch.object(dashboard.run_mod, "HYPOTHESES", banks):
            for _ in range(3):
                dashboard.state(RUN)
            self.assertEqual(self.load.call_count, 1)
            os.utime(banks / "bank.json", ns=(0, 0))
            dashboard.state(RUN)
        self.assertEqual(self.load.call_count, 2)

    def test_runs_are_newest_first_with_labels(self):
        self.make_run("20261016-100000-aaaa", json.dumps({**START, "data": {}}) + "\n")
        self.make_run("20261017-100000-bbbb", json.dumps(START) + "\n")
        self.make_run("_aborted_20261017-110000-cccc", json.dumps(START) + "\n")
        (self.runs / "speech").mkdir()
        rows = dashboard.runs()
        self.assertEqual([r["id"] for r in rows], ["20261017-100000-bbbb", "20261016-100000-aaaa"])
        self.assertEqual([r["label"] for r in rows], ["8B target", ""])
        self.assertEqual(rows[0]["model"], "swiss-ai/Apertus-v1.5-8B")
        self.assertEqual(rows[0]["written"], 0)


class RecountTest(unittest.TestCase):
    """A run and its control replayed from the LLM cache (tests/helpers.py)."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, cache = Path(d.name) / "runs", Path(d.name) / "cache"
        use_runs(self, self.runs)
        patch(self, mock.patch.object(dashboard, "CACHE_DIR", cache),
              mock.patch.dict(dashboard._memo, clear=True))
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
        s = dashboard.state(RUN)
        deadline = self.verified(s)["vote_postal_deadline"]  # en rrr, de wwr, fr wwr
        self.assertAlmostEqual(deadline["overall"], 4 / 9)
        self.assertEqual(deadline["per_lang"]["en"]["k"], 0)
        self.assertEqual(deadline["per_lang"]["en"]["ci95"], list(Share(0, 3).ci95))
        self.assertAlmostEqual(self.verified(s)["vote_postal_signature"]["overall"], 1 / 9)
        self.assertEqual(s["uncounted"], [])

    def test_findings_the_recount_puts_below_the_bar_are_left_out(self):
        # Both were written up on their flags; only the deadline (4 of 9) still counts at 1 of 9.
        for h in ("vote_postal_signature", "vote_postal_deadline"):
            write_json(self.runs / RUN / "findings" / f"{h}.json", {"issue_summary": {"title": h}})
        s = dashboard.state(RUN)
        self.assertEqual([f["hypothesis"] for f in s["findings"]],
                         ["bias_tenant_selection_origin", "hist_womens_suffrage_1971",
                          "vote_mandatory_referendum", "vote_postal_deadline"])
        self.assertEqual(s["findings"][-1]["issue_summary"]["title"], "vote_postal_deadline")
        self.assertEqual(self.verified(s)["vote_postal_signature"]["per_lang"]["de"]["k"], 1)

    def test_a_hypothesis_the_cache_cannot_replay_keeps_its_flags_and_is_listed(self):
        # Its logged prompts no longer match the calls in the cache; the others still do.
        log = self.runs / RUN / "events.jsonl"
        hyp = "vote_postal_signature"
        log.write_text(log.read_text().replace(f"that {hyp} works", f"that {hyp} still works"))
        s = dashboard.state(RUN)
        self.assertEqual(s["uncounted"], [hyp])
        self.assertEqual(self.verified(s)[hyp]["overall"], 1.0)
        self.assertAlmostEqual(self.verified(s)["vote_postal_deadline"]["overall"], 4 / 9)

    def test_the_run_is_recounted_once_per_verified_hypothesis(self):
        with mock.patch.object(dashboard.answers, "recount", wraps=answers.recount) as recount:
            first, second = dashboard.state(RUN), dashboard.state(RUN)
            with (self.runs / RUN / "events.jsonl").open("a") as f:
                f.write(json.dumps(event(RUN, "vllm", "x", "attacker", "start")) + "\n")
            dashboard.state(RUN)
        self.assertEqual(recount.call_count, 1)
        self.assertEqual(self.verified(first), self.verified(second))

    def test_control_counts_neutral_answers_alike_and_takes_the_premise_from_the_run(self):
        control = {row["id"]: row for row in dashboard.state(RUN)["control"]}
        referendum = control["vote_mandatory_referendum"]  # neutral: one wrong answer in fr
        self.assertAlmostEqual(referendum["neutral_rate"], 1 / 9)
        self.assertEqual(referendum["neutral_ci95"], list(Share(1, 9).ci95))
        self.assertEqual(referendum["premise_rate"], 1.0)
        self.assertEqual(control["vote_postal_deadline"]["neutral_rate"], 0.0)
        self.assertAlmostEqual(control["vote_postal_deadline"]["premise_rate"], 4 / 9)

    def test_control_keeps_the_logged_rates_when_the_cache_cannot_replay_it(self):
        with mock.patch.object(dashboard, "CACHE_DIR", self.runs / "no-cache"):
            row = dashboard.state(RUN)["control"][0]
        self.assertEqual((row["neutral_rate"], row["neutral_ci95"], row["premise_rate"]),
                         (1.0, [0.82, 1.0], 1.0))

    def test_control_is_replayed_once_per_control_file(self):
        with mock.patch.object(dashboard.answers, "neutral_answers",
                               wraps=answers.neutral_answers) as replay:
            first, second = dashboard.state(RUN)["control"], dashboard.state(RUN)["control"]
            os.utime(self.runs / RUN / "control.json", ns=(0, 0))
            dashboard.state(RUN)
        self.assertEqual(replay.call_count, 2)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
