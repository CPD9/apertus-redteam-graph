import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["REDTEAM_BACKEND"] = "mock"

from helpers import GRID, LANGS, REFS, event, use_runs, write_run  # noqa: E402
from redteam import control, llm  # noqa: E402
from redteam.events import read_events  # noqa: E402
from redteam.graph import Config, run  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

HYPS = load_hypotheses()[:3]


class Recording(llm.MockLLM):
    """The MOCK, noting the system prompt of every request to the target."""

    def __init__(self):
        self.systems = []

    def chat(self, messages, *, role, **kw):
        if role == "target":
            self.systems.append(messages[0]["content"] if messages[0]["role"] == "system" else None)
        return super().chat(messages, role=role, **kw)


class NoJSON(llm.MockLLM):
    """The MOCK, except that the attacker never replies with JSON."""

    def chat(self, messages, *, role, **kw):
        if role == "attacker":
            return "no JSON here"
        return super().chat(messages, role=role, **kw)


class ControlTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs = Path(d.name) / "runs"  # its sibling folders stay inside d as well
        use_runs(self, self.runs)
        patcher = mock.patch.object(control, "load_hypotheses", return_value=HYPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def control(self, system=None, edit=None) -> tuple[dict, list[dict], list]:
        """A MOCK run, then its control; returns the run, the control rows and the system prompts
        the control sent to the target. `edit` may change the run folder in between."""
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs, system=system))
        if edit:
            edit(self.runs / summary["run_id"])
        target = Recording()
        with mock.patch.object(control.llm_mod, "detect", return_value=target), \
                contextlib.redirect_stdout(io.StringIO()):
            control.main(["--run", summary["run_id"]])
        rows = json.loads((self.runs / summary["run_id"] / "control.json").read_text())
        return summary, rows, target.systems

    @staticmethod
    def counted(run_dir: Path) -> dict[str, dict]:
        return {e["hypothesis"]: e["data"]["counted"] for e in read_events(run_dir / "events.jsonl")
                if (e["node"], e["status"]) == ("verifier", "done")}

    def test_control_compares_premise_and_neutral_rates(self):
        summary, rows, _ = self.control()
        written = [r["id"] for r in summary["results"] if r.get("path")]
        self.assertTrue(written)
        self.assertEqual(sorted(r["id"] for r in rows), sorted(written))
        for row in rows:
            self.assertEqual(len(row["neutral_answers"]["en"]), len(Config().verify_seeds))
            self.assertLessEqual(row["neutral_ci95"][0], row["neutral_rate"])

    def test_control_asks_with_the_system_prompt_of_the_run(self):
        _, rows, systems = self.control(system="Check the premise first.")
        self.assertTrue(rows)
        self.assertEqual(set(systems), {"Check the premise first."})

    def test_a_run_without_system_prompt_gets_a_control_without_one(self):
        _, _, systems = self.control()
        self.assertEqual(set(systems), {None})

    def test_the_premise_side_is_counted_from_the_run_not_from_an_old_findings_file(self):
        def old_format(run_dir):
            # Findings files written before the counting rule held the share the judge flagged.
            for f in (run_dir / "findings").glob("*.json"):
                finding = json.loads(f.read_text())
                params = finding["model"]["parameters"]
                del params["harness_flagged_rate"]
                params["harness_overall_rate"] = 0.987
                params["harness_reproduction_rates"] = dict.fromkeys(params["harness_langs"], 0.987)
                f.write_text(json.dumps(finding))

        summary, rows, _ = self.control(edit=old_format)
        counted = self.counted(self.runs / summary["run_id"])
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["premise_rate"], counted[row["id"]]["overall"])
            self.assertEqual(row["premise_by_lang"], counted[row["id"]]["rates"])

    def test_hypotheses_counted_below_the_bar_get_no_row(self):
        def below(run_dir):
            log = run_dir / "events.jsonl"
            events = read_events(log)
            done = [e for e in events if (e["node"], e["status"]) == ("verifier", "done")
                    and (run_dir / "findings" / f"{e['hypothesis']}.json").exists()]
            done[0]["data"]["counted"]["overall"] = 0.1
            self.dropped = done[0]["hypothesis"]
            log.write_text("".join(json.dumps(e) + "\n" for e in events))

        summary, rows, _ = self.control(edit=below)
        written = {r["id"] for r in summary["results"] if r.get("path")}
        self.assertIn(self.dropped, written)
        self.assertEqual({r["id"] for r in rows}, written - {self.dropped})

    def test_a_recorded_run_in_data_runs_keeps_its_control(self):
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs))
        shipped = self.runs.with_name(self.runs.name + "-shipped")
        recorded = shipped / summary["run_id"]
        recorded.mkdir(parents=True)
        shutil.copy(self.runs / summary["run_id"] / "events.jsonl", recorded)
        (recorded / "control.json").write_text('[{"id": "recorded"}]')
        use_runs(self, self.runs.with_name("empty-runs"), shipped)
        with mock.patch.object(control.llm_mod, "detect", side_effect=AssertionError), \
                contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            control.main(["--run", summary["run_id"]])
        self.assertIn("is a recorded run", err.getvalue())
        self.assertEqual((recorded / "control.json").read_text(), '[{"id": "recorded"}]')

    def test_a_control_where_no_row_can_be_asked_keeps_the_old_control_json(self):
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs))
        out = self.runs / summary["run_id"] / "control.json"
        out.write_text("[1]")
        with mock.patch.object(control.llm_mod, "detect", return_value=NoJSON()), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            control.main(["--run", summary["run_id"]])
        self.assertIn("could be asked neutrally", str(stop.exception))
        self.assertEqual(out.read_text(), "[1]")

    def test_a_run_without_findings_files_is_a_usage_error(self):
        summary = run(llm.MockLLM(), HYPS, Config(out_dir=self.runs))
        folder = self.runs / summary["run_id"]
        shutil.rmtree(folder / "findings")
        (folder / "control.json").write_text("[1]")
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            control.main(["--run", summary["run_id"]])
        self.assertIn("no reproduced hypothesis", err.getvalue())
        self.assertEqual((folder / "control.json").read_text(), "[1]")

    def test_unknown_run_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            control.main(["--run", "nope"])
        self.assertIn("no run nope", err.getvalue())


class PremisesTest(unittest.TestCase):
    """A run logged before the counting rule: its verifier results hold only the judge's flags."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, self.cache = Path(d.name) / "runs", Path(d.name) / "cache"
        write_run(self.runs, self.cache, "r8b")
        every = {lang: {"k": 3, "n": 3, "rate": 1.0} for lang in LANGS}
        with (self.runs / "r8b" / "events.jsonl").open("a") as f:
            for h in GRID:
                f.write(json.dumps(event("r8b", "vllm", h, "verifier", "done",
                                         per_lang=every, overall=1.0)) + "\n")

    def test_logged_flags_are_recounted_from_the_cache(self):
        premise = control.premises(self.runs / "r8b", REFS, self.cache)
        self.assertEqual(set(premise), set(GRID))
        deadline = premise["vote_postal_deadline"]  # en rrr, de wwr, fr wwr
        self.assertAlmostEqual(deadline["overall"], 4 / 9)
        self.assertEqual({lang: c["k"] for lang, c in deadline["per_lang"].items()},
                         {"en": 0, "de": 2, "fr": 2})

    def test_a_hypothesis_the_cache_cannot_replay_is_left_out(self):
        log = self.runs / "r8b" / "events.jsonl"
        hyp = "vote_postal_signature"
        log.write_text(log.read_text().replace(f"that {hyp} works", f"that {hyp} still works"))
        premise = control.premises(self.runs / "r8b", REFS, self.cache)
        self.assertEqual(set(premise), set(GRID) - {hyp})


if __name__ == "__main__":
    unittest.main()
