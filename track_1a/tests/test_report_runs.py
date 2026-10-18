"""Recorded runs as the report reads them: counted from the LLM cache like the findings, or with
the judge's logged flags, and a run counted hypothesis by hypothesis."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src"), str(TRACK / "tests")]

import helpers  # noqa: E402
import report_figures as figures  # noqa: E402
import report_runs as runs  # noqa: E402
from report_helpers import (JUDGE, Isolated, events_of, finish_verification, quietly,  # noqa: E402
                            write_logged_run)
from redteam.shares import Share  # noqa: E402


class LoggedRunTest(Isolated):
    def test_run_in_progress_with_a_half_written_line(self):
        run = write_logged_run(self.root, "r70", "m/70B", {"a": [3, 3, 3]}, finished=False)
        with (run / "events.jsonl").open("a") as f:
            f.write('{"t": 1, "run_id": "r70", "hyp')
        loaded, notes = quietly(runs.recorded, run)
        self.assertEqual(list(loaded.verified), ["a"])
        self.assertIn("still in progress", notes)

    def test_served_alias_matches_the_full_model_id(self):
        self.assertTrue(runs.same_model(JUDGE, "onprem-ai/Apertus-v1.5-70B-FP8"))
        self.assertFalse(runs.same_model(JUDGE, "swiss-ai/Apertus-v1.5-8B"))


class CountedRunTest(Isolated):
    """A run replayed from its LLM cache (helpers.write_run), so the figures count only answers
    that state the error, as the findings do."""
    def setUp(self):
        super().setUp()
        self.replay("r8")
        helpers.write_control(self.runs, self.cache, "r8")
        finish_verification(self.runs / "r8")

    def test_recorded_run_counts_only_answers_that_state_the_error(self):
        logged = next(e["data"] for e in events_of(self.runs / "r8")
                      if e["hypothesis"] == "vote_postal_signature"
                      and (e["node"], e["status"]) == ("verifier", "done"))
        self.assertEqual(logged["overall"], 1.0)  # each answer lists the premise, so all flagged
        rec, notes = quietly(runs.recorded, "r8")
        self.assertEqual((notes, rec.uncounted), ("", set()))
        counted = rec.verified["vote_postal_signature"]
        self.assertEqual({lang: c["k"] for lang, c in counted["per_lang"].items()},
                         {"en": 0, "de": 1, "fr": 0})
        self.assertAlmostEqual(counted["overall"], 1 / 9)

    def test_figures_count_like_the_findings(self):
        rec, _ = quietly(runs.recorded, "r8")
        _, heat = figures.gap_heatmap(rec)
        rows = {r["id"]: r for r in heat["rows"]}
        self.assertEqual(rows["vote_postal_signature"]["label"], "Postal vote signature")
        self.assertFalse(rows["vote_postal_signature"]["reproduced"])
        self.assertTrue(rows["vote_mandatory_referendum"]["reproduced"])
        (_, premise), notes = quietly(figures.premise_vs_neutral, rec)
        self.assertEqual(notes, "")
        self.assertEqual(premise["excluded"], ["vote_postal_deadline"])
        [row] = premise["rows"]
        self.assertEqual((row["id"], row["premise_rate"], row["neutral_rate"]),
                         ("vote_mandatory_referendum", 1.0, round(1 / 9, 4)))

    def test_a_control_row_missing_from_the_cache_keeps_its_logged_rates(self):
        path = self.runs / "r8" / "control.json"
        rows = json.loads(path.read_text())
        for row in rows:
            row.update(premise_rate=0.0, neutral_rate=1.0)
        broken, replayed = rows
        broken["neutral_answers"]["en"][0] += " Not in the cache."
        path.write_text(json.dumps(rows))
        rec, _ = quietly(runs.recorded, "r8")
        shares, notes = quietly(runs.control_shares, rec, rows)
        self.assertIn("1 of 2 rows cannot be replayed", notes)
        self.assertEqual(shares[broken["id"]], (Share(0, 9), Share(9, 9)))  # as logged
        self.assertEqual(shares[replayed["id"]], (Share(4, 9), Share(0, 9)))  # as counted

    def test_answers_missing_from_the_cache_keep_the_logged_flags(self):
        with mock.patch.object(runs, "CACHE", self.root / "empty"):
            rec, notes = quietly(runs.recorded, "r8")
        self.assertIn(f"{len(helpers.GRID)} of {len(helpers.GRID)} verified hypotheses cannot "
                      "be replayed", notes)
        self.assertEqual(rec.verified["vote_postal_signature"]["overall"], 1.0)


class BankCountTest(Isolated):
    """A run that no finding groups, counted hypothesis by hypothesis for numbers.json (bank 2)."""
    def setUp(self):
        super().setUp()
        self.replay("r70", failed=["tenancy_contest_termination"])

    def counts(self):
        numbers, notes = quietly(runs.hypothesis_counts, "r70")
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
            numbers, notes = quietly(runs.hypothesis_counts, "r70")
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
