"""A run that no finding groups, counted hypothesis by hypothesis for numbers.json (bank 2)."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src"), str(TRACK / "tests")]

import helpers  # noqa: E402
import report_bank as bank  # noqa: E402
import report_figures as figures  # noqa: E402
import report_runs as runs  # noqa: E402
from report_helpers import Isolated, events_of, finish_verification, quietly  # noqa: E402


class BankCountTest(Isolated):
    def setUp(self):
        super().setUp()
        self.runs, self.cache = self.root / "runs", self.root / "cache"
        helpers.write_run(self.runs, self.cache, "r70", failed=["tenancy_contest_termination"])
        helpers.use_runs(self, self.runs)
        patcher = mock.patch.object(runs, "CACHE", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def counts(self):
        numbers, notes = quietly(bank.hypothesis_counts, "r70")
        return {r["id"]: r for r in numbers["rows"]}, notes

    def stop_with_an_error(self, hyp):
        """The run as if a judge reply had not parsed after the last verified answer of hyp."""
        log = self.runs / "r70" / "events.jsonl"
        events = [e for e in events_of(self.runs / "r70")
                  if not (e["hypothesis"] == hyp and e["node"] in ("scribe", "graph"))]
        events.append(helpers.event("r70", "vllm", hyp, "graph", "error", error="JSONDecodeError"))
        log.write_text("".join(json.dumps(e) + "\n" for e in events))

    def test_each_hypothesis_counts_the_answers_that_state_the_error(self):
        rows, notes = self.counts()
        self.assertEqual(notes, "")
        self.assertEqual(list(rows), [*helpers.GRID, "tenancy_contest_termination"])
        deadline = rows["vote_postal_deadline"]  # en rrr, de wwr, fr wwr
        self.assertEqual((deadline["k"], deadline["n"], deadline["status"]), (4, 9, "finding"))
        self.assertTrue(deadline["reproduced"])
        signature = rows["vote_postal_signature"]  # flagged 9 of 9, but only 1 states the error
        self.assertEqual((signature["k"], signature["status"]), (1, "finding"))
        self.assertFalse(signature["reproduced"])
        self.assertEqual(rows["vote_mandatory_referendum"]["title"], "Mandatory referendum")

    def test_a_hypothesis_that_stopped_keeps_its_answers_but_is_not_reproduced(self):
        self.stop_with_an_error("hist_womens_suffrage_1971")
        rows, _ = self.counts()
        stopped = rows["hist_womens_suffrage_1971"]
        self.assertEqual((stopped["k"], stopped["n"], stopped["status"]), (9, 9, "error"))
        self.assertFalse(stopped["reproduced"])
        never = rows["tenancy_contest_termination"]
        self.assertEqual((never["k"], never["n"], never["reproduced"]), (0, 0, False))

    def test_hypotheses_missing_from_the_cache_are_named(self):
        with mock.patch.object(runs, "CACHE", self.root / "empty"):
            numbers, notes = quietly(bank.hypothesis_counts, "r70")
        self.assertEqual(numbers["unreplayed"], list(helpers.GRID))
        self.assertIn(f"{len(helpers.GRID)} hypotheses cannot be replayed", notes)
        self.assertFalse(any(r["reproduced"] for r in numbers["rows"]))

    def test_numbers_json_holds_the_counts_only_when_asked(self):
        for extra, out in (([], self.root / "plain"), (["--bank2", "r70"], self.root / "bank2")):
            quietly(figures.main, ["--canonical", "r70", *extra, "--out", str(out)])
            numbers = json.loads((out / "numbers.json").read_text())
            self.assertEqual("bank2" in numbers, bool(extra))
        self.assertEqual(numbers["bank2"]["run"], "r70")
        self.assertEqual(len(numbers["bank2"]["rows"]), len(helpers.GRID) + 1)
        self.assertFalse((out / "bank2.svg").exists())

    def test_an_unknown_bank2_run_stops_before_any_figure_is_written(self):
        finish_verification(self.runs / "r70")  # so the heatmap has something to draw
        out = self.root / "figures"
        quietly(figures.main, ["--canonical", "r70", "--out", str(out)])
        self.assertTrue((out / "gap_heatmap.svg").exists())
        empty = self.root / "empty"
        empty.mkdir()
        args = ["--canonical", "r70", "--bank2", "no-such-run", "--out", str(empty)]
        with self.assertRaises(SystemExit):
            quietly(figures.main, args)
        self.assertEqual(list(empty.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
