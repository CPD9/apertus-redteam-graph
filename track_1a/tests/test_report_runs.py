"""Recorded runs as the report reads them: counted from the LLM cache like the findings, or with
the judge's logged flags, and rates pooled over hypotheses."""
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
from redteam.answers import Share  # noqa: E402
from redteam.stats import wilson  # noqa: E402


class LoggedRunTest(Isolated):
    def test_run_in_progress_with_a_half_written_line(self):
        run = write_logged_run(self.root, "r70", "m/70B", {"a": [3, 3, 3]}, finished=False)
        with (run / "events.jsonl").open("a") as f:
            f.write('{"t": 1, "run_id": "r70", "hyp')
        loaded, notes = quietly(runs.recorded, run)
        self.assertEqual(list(loaded.verified), ["a"])
        self.assertIn("still in progress", notes)

    def test_pooled_interval_resamples_hypotheses(self):
        # every hypothesis is either always or never violated, so the answers are clustered
        table = [(3, 3)] * 10 + [(0, 3)] * 10
        result = runs.pooled(table, runs.resamples(len(table)))
        low, high = result["ci95"]
        wilson_low, wilson_high = wilson(30, 60)
        self.assertEqual(result["rate"], 0.5)
        self.assertLess(low, wilson_low)
        self.assertGreater(high, wilson_high)

    def test_each_hypothesis_is_compared_with_the_attack_it_ended_with(self):
        small = write_logged_run(self.root, "r8", "m/8B", {"a": [1, 1, 1], "b": [2, 2, 2]})
        large = write_logged_run(self.root, "r70", "m/70B", {"a": [0, 0, 0]}, unbroken=["b"])
        tried = {small: [("a", "false_premise"), ("b", "false_premise"), ("b", "practical_need")],
                 large: [("a", "false_premise"), ("b", "authority_role"), ("b", "code_switch")]}
        for run, attempts in tried.items():
            with (run / "events.jsonl").open("a") as f:
                for hyp, strategy in attempts:
                    f.write(json.dumps({"t": 1, "run_id": run.name, "hypothesis": hyp,
                                        "node": "attacker", "status": "done",
                                        "data": {"strategy": strategy, "prompt": "p"}}) + "\n")
        before, after = (quietly(runs.recorded, run)[0] for run in tried)
        numbers = runs.comparison(before, after, ["8B", "70B"])
        self.assertEqual(numbers["last_attack"],
                         {"8B": {"false_premise": 1, "practical_need": 1},
                          "70B": {"false_premise": 1, "code_switch": 1}})
        self.assertEqual(numbers["other_last_attack"],
                         {"8B": {"b": "practical_need"}, "70B": {"b": "code_switch"}})

    def test_served_alias_matches_the_full_model_id(self):
        self.assertTrue(runs.same_model(JUDGE, "onprem-ai/Apertus-v1.5-70B-FP8"))
        self.assertFalse(runs.same_model(JUDGE, "swiss-ai/Apertus-v1.5-8B"))


class CountedRunTest(Isolated):
    """A run replayed from its LLM cache (helpers.write_run), so the figures count only answers
    that state the error, as the findings do."""
    def setUp(self):
        super().setUp()
        self.runs, self.cache = self.root / "runs", self.root / "cache"
        helpers.write_run(self.runs, self.cache, "r8")
        helpers.write_control(self.runs, self.cache, "r8")
        finish_verification(self.runs / "r8")
        helpers.use_runs(self, self.runs)
        patcher = mock.patch.object(runs, "CACHE", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

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


if __name__ == "__main__":
    unittest.main()
