import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK / "src"))

from redteam import (group, paths, report_table, reproduce, speech_finding,  # noqa: E402
                     speech_scores)
from redteam.cache import CACHE_DIR, PACK  # noqa: E402

SPEECH = speech_finding.FINDING.stem


def written(finding: dict) -> str:
    return json.dumps(finding, indent=2, ensure_ascii=False) + "\n"


class ReproduceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Runs only from data/runs/ and model calls only from the pack, as in a fresh checkout.
        tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.enterClassContext(mock.patch.object(paths, "RUNS", tmp / "runs"))
        cache = tmp / "cache"
        cache.mkdir()
        (cache / PACK).symlink_to(CACHE_DIR / PACK)
        cls.enterClassContext(mock.patch.object(group, "CACHE_DIR", cache))
        # The submitted findings name the runs; what is compared is written fresh from them, so
        # these tests do not depend on findings/ being up to date (the reproduce step checks that).
        submitted = {path.stem: json.loads(path.read_text())
                     for path in (TRACK / "findings").glob("*.json")}
        themes = {t["id"] for t in group.THEMES}
        cls.rebuilt, unbuilt = reproduce.rebuild({k: f for k, f in submitted.items()
                                                  if k in themes})
        assert not unbuilt, unbuilt
        cls.fresh = {**cls.rebuilt, SPEECH: speech_scores.rebuild(submitted[SPEECH])}

    def setUp(self):
        self.findings = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(mock.patch.object(reproduce, "FINDINGS", self.findings))
        for name, finding in self.fresh.items():
            self.write(name, finding)

    def write(self, name: str, finding: dict) -> None:
        (self.findings / f"{name}.json").write_text(written(finding))

    def edited(self, name: str, edit) -> None:
        finding = json.loads((self.findings / f"{name}.json").read_text())
        edit(finding)
        self.write(name, finding)

    def reproduce(self) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = reproduce.main([])
        return code, out.getvalue()

    def test_findings_equal_to_their_rebuild_pass_and_print_the_summary_table(self):
        self.assertEqual(set(self.rebuilt), {t["id"] for t in group.THEMES})
        code, out = self.reproduce()
        self.assertEqual(code, 0, out)
        for theme in group.THEMES:
            self.assertIn(f"findings/{theme['id']}.json matches its rebuild", out)
        self.assertIn(f"findings/{SPEECH}.json matches its rebuild from data/runs/speech/", out)
        self.assertTrue(out.endswith(report_table.table(reproduce.in_report_order(
            {p.stem: p.read_text() for p in self.findings.glob("*.json")})) + "\n"))

    def test_a_sentence_changed_by_hand_fails_and_shows_where(self):
        def edit(f):
            f["issue_summary"]["overview"] += " Checked by hand."
        self.edited("civic_sycophancy", edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("findings/civic_sycophancy.json differs from its rebuild:\n"
                      "  issue_summary.overview:\n    findings/ ", out)
        self.assertIn(' Checked by hand."', out)
        self.assertIn("findings/pension_rules.json matches its rebuild", out)
        self.assertNotIn("| Finding |", out)

    def test_a_rate_changed_by_hand_fails(self):
        def edit(f):
            f["model"]["parameters"]["harness_variations"][0]["k"] -= 1
        self.edited("safety_knowledge_gaps", edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("  model.parameters.harness_variations[0].k:\n", out)

    def test_a_speech_number_changed_by_hand_fails(self):
        def edit(f):
            f["model"]["parameters"]["unrelated"]["all"]["apertus"]["k"] += 1
        self.edited(SPEECH, edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn(f"findings/{SPEECH}.json differs from its rebuild from data/runs/", out)
        self.assertIn("  model.parameters.unrelated.all.apertus.k:\n", out)

    def test_a_number_in_the_speech_text_changed_by_hand_fails(self):
        def edit(f):
            f["issue_title"] = f["issue_title"].replace("(1%)", "(9%)")
            f["issue_summary"]["overview"] = f["issue_summary"]["overview"].replace("48%", "58%")
            f["model"]["parameters"]["temperature"] = 0.9
        self.edited(SPEECH, edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        for where in ("issue_title", "model.parameters.temperature", "issue_summary.overview"):
            self.assertIn(f"\n  {where}:\n", out)
        self.assertIn("(9%)", out)
        self.assertIn("58%", out)

    def test_a_walkthrough_that_is_not_a_recorded_clip_fails(self):
        def edit(f):
            f["apertus_response_walkthroughs"][0] = f["apertus_response_walkthroughs"][0].replace(
                "sentence", "sentence 1", 1)
        self.edited(SPEECH, edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("  apertus_response_walkthroughs: length 10 in findings/, 9 in the rebuild",
                      out)

    def test_a_run_that_is_not_there_fails_with_its_reason(self):
        def edit(f):
            f["model"]["parameters"]["harness_run_id"] = "20990101-000000-none"
        self.edited("pension_rules", edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("findings/pension_rules.json differs from its rebuild:\n  cannot rebuild "
                      "it: no run 20990101-000000-none in runs/ or data/runs/\n", out)
        self.assertIn("findings/civic_sycophancy.json matches its rebuild", out)

    def test_calls_missing_from_the_cache_fail_with_the_reason(self):
        with mock.patch.object(group, "CACHE_DIR", self.findings / "empty"), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("findings/civic_sycophancy.json differs from its rebuild:\n  cannot rebuild "
                      "it: ", out)
        self.assertIn("not in cache", out)
        self.assertEqual(err.getvalue(), "")

    def test_speech_scores_without_a_setting_the_finding_needs_fail(self):
        scores = json.loads(speech_scores.path_of(self.fresh[SPEECH]["model"]["parameters"]
                                                  ["harness_run_id"]).read_text())
        del scores["instruction"]
        shipped = self.findings / "shipped"
        path = shipped / scores["run_id"] / "scores.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(scores))
        with mock.patch.object(speech_scores, "SPEECH", shipped), \
                mock.patch.object(paths, "ROOT", self.findings):
            code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn(f"  cannot rebuild it: shipped/{scores['run_id']}/scores.json has no "
                      "'instruction'", out)

    def test_missing_speech_scores_fail(self):
        def edit(f):
            f["model"]["parameters"]["harness_run_id"] = "20990101-000000"
        self.edited(SPEECH, edit)
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("  cannot rebuild it: data/runs/speech/20990101-000000/scores.json does not "
                      "exist", out)

    def test_the_same_content_written_differently_fails(self):
        path = self.findings / "pension_rules.json"
        path.write_text(json.dumps(json.loads(path.read_text()), indent=1))
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("same content, written differently", out)

    def test_a_missing_finding_fails(self):
        (self.findings / "pension_rules.json").unlink()
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("findings/pension_rules.json differs from the findings this repository "
                      "builds:\n  the file is missing", out)

    def test_a_finding_no_generator_writes_fails(self):
        self.write("example_findings", self.rebuilt["civic_sycophancy"])
        code, out = self.reproduce()
        self.assertEqual(code, 1)
        self.assertIn("findings/example_findings.json differs from the findings this repository "
                      "builds:\n  no generator writes it", out)


class DifferencesTest(unittest.TestCase):
    def test_paths_name_each_difference(self):
        want = {"a": {"b": [1, 2]}, "c": "x", "gone": 1, "list": [1]}
        got = {"a": {"b": [1, 3]}, "c": "x", "new": 1, "list": [1, 2]}
        self.assertEqual(reproduce.differences(want, got), [
            "a.b[1]:", "  findings/ 2", "  rebuilt   3",
            "gone: only in findings/",
            "list: length 1 in findings/, 2 in the rebuild",
            "new: only in the rebuild"])

    def test_long_texts_show_where_they_first_differ(self):
        want, got = "x" * 500 + "old" + "y" * 500, "x" * 500 + "new" + "y" * 500
        lines = reproduce.differences({"t": want}, {"t": got})
        self.assertEqual(lines[1], '  findings/ ..."' + "x" * 60 + "old" + "y" * 57 + '"...')
        self.assertEqual(lines[2], '  rebuilt   ..."' + "x" * 60 + "new" + "y" * 57 + '"...')


class ScoresTest(unittest.TestCase):
    def test_scores_keep_no_text_of_the_clips(self):
        clip = {"dialect": "be", "sentence_id": 7, "gold": "Referenz", "output": "Ausgabe",
                "chrf": 41.2, "hallucinated": True, "meaning": "unrelated"}
        results = {"model": "m", "judge": "j", "instruction": "Translate.", "temperature": 0,
                   "data_dir": "/home/someone/swissdial", "clips": [clip]}
        compare = {"whisper_model": "w", "whisper_clips": [{**clip, "meaning": "same"}]}
        s = speech_scores.scores(results, compare, "r1")
        self.assertEqual(s["apertus"], [{"dialect": "be", "sentence_id": 7, "chrf": 41.2,
                                         "meaning": "unrelated"}])
        self.assertEqual(s["whisper"][0]["meaning"], "same")
        self.assertEqual(s["instruction"], "Translate.")
        for text in ("Referenz", "Ausgabe", "swissdial"):
            self.assertNotIn(text, json.dumps(s))

    def test_shipped_scores_hold_only_dialect_sentence_score_and_verdict(self):
        shipped = list(speech_scores.SPEECH.glob("*/scores.json"))
        self.assertTrue(shipped)
        for path in shipped:
            s = json.loads(path.read_text())
            self.assertEqual(set(s), {"run_id", *speech_scores.SETTINGS, "whisper_model",
                                      "apertus", "whisper"})
            clips = s["apertus"] + s["whisper"]
            self.assertEqual({key for clip in clips for key in clip}, set(speech_scores.SCORED))
            self.assertLessEqual({clip["meaning"] for clip in clips},
                                 {*speech_finding.RATED, "unknown"})


class ReportTableTest(unittest.TestCase):
    def setUp(self):
        self.findings = {p.stem: p.read_text() for p in (TRACK / "findings").glob("*.json")}

    def test_the_report_shows_the_table_reproduce_prints(self):
        table = report_table.table(reproduce.in_report_order(self.findings))
        self.assertIn("\n" + table + "\n", (TRACK / "technical_report.md").read_text())

    def test_the_pooled_rate_is_the_one_the_finding_states(self):
        safety = json.loads(self.findings["safety_knowledge_gaps"])
        p = safety["model"]["parameters"]
        # The interval resamples variations and languages; the table prints it as stated.
        self.assertEqual(p["harness_overall_ci95"], [0.375, 0.958])
        self.assertIn("| 71% (38–96) |", report_table.table([safety]))
        p["harness_overall_rate"] = 0.5  # as if group pooled another way
        with self.assertRaisesRegex(ValueError, "not to the overall rate the finding states"):
            report_table.table([safety])


if __name__ == "__main__":
    unittest.main()
