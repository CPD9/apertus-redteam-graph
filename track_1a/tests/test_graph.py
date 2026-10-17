import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["REDTEAM_BACKEND"] = "mock"

from redteam import llm, models, paths, run as run_mod, scribe, walkthrough  # noqa: E402
from redteam.events import read_events  # noqa: E402
from redteam.graph import Config, run  # noqa: E402
from redteam.run import load_hypotheses, print_results  # noqa: E402

SEEDS = load_hypotheses()[:5]


class CorrectingLLM(llm.MockLLM):
    """Every answer corrects the user: the claims check flags it, the judge rates it 0."""

    def chat(self, messages, *, role, **kw):
        if role == "judge":
            return json.dumps({"claims": [{"claim": "the premise", "verdict": "contradicted"}],
                               "behavior_violation": False, "severity": 0, "reason": "corrects",
                               "evidence": ""})
        return super().chat(messages, role=role, **kw)


class GraphTest(unittest.TestCase):
    def test_mock_run_produces_schema_valid_findings(self):
        with tempfile.TemporaryDirectory() as d:
            summary = run(llm.MockLLM(), SEEDS, Config(out_dir=Path(d)))
            self.assertEqual(summary["backend"], "MOCK")
            self.assertEqual(len(summary["results"]), len(SEEDS))
            self.assertFalse([r for r in summary["results"] if r["status"] == "error"])
            files = list(Path(d).glob("*/findings/*.json"))
            self.assertGreaterEqual(len(files), 1)
            self.assertEqual(len(files), sum(bool(r.get("path")) for r in summary["results"]))
            for f in files:
                finding = json.loads(f.read_text())
                self.assertEqual(scribe.validate(finding), [], f.name)
                self.assertTrue(finding["issue_title"].startswith("[MOCK]"))
                self.assertEqual(finding["environment"], scribe.MOCK_ENVIRONMENT)
                self.assertIn("REDTEAM_BACKEND=mock", finding["steps_to_reproduce"][0])

    def test_walkthroughs_use_the_apertus_chat_template(self):
        start = walkthrough.TEMPLATE["user_assistant"].split("<<USER>>")[0]
        own = "<s><|system_start|>Check the premise.<|system_end|>"
        for system, prefix in ((None, start), ("Check the premise.", own)):
            with tempfile.TemporaryDirectory() as d:
                run(llm.MockLLM(), SEEDS, Config(out_dir=Path(d), system=system))
                finding = json.loads(next(Path(d).glob("*/findings/*.json")).read_text())
            for conversation in finding["apertus_response_walkthroughs"]:
                self.assertTrue(conversation.startswith(prefix), conversation[:80])
                self.assertIn("deliberately wrong", conversation)
            self.assertEqual(finding["model"]["parameters"]["harness_system_prompt"], system)

    @staticmethod
    def first_finding(backend: str, hardware: str | None = None) -> dict:
        class Served(llm.MockLLM):
            model, red_model = "onprem-ai/Apertus-v1.5-70B-FP8", "apertus-70b-fp8"
        Served.backend = backend
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ):
            os.environ.pop("REDTEAM_HARDWARE", None)
            if hardware:
                os.environ["REDTEAM_HARDWARE"] = hardware
            run(Served(), SEEDS, Config(out_dir=Path(d)))
            return json.loads(next(Path(d).glob("*/findings/*.json")).read_text())

    def test_live_findings_do_not_guess_the_hardware(self):
        finding = self.first_finding("vllm")
        self.assertEqual(finding["environment"]["hardware"], "not recorded")
        named = self.first_finding("vllm", hardware="1 x NVIDIA H100")
        self.assertEqual(named["environment"]["hardware"], "1 x NVIDIA H100")
        target = "onprem-ai/Apertus-v1.5-70B-FP8"
        self.assertEqual(finding["model"]["version"], models.REVISIONS[target])
        self.assertEqual(finding["model"]["provider"], "onprem-ai")
        params = finding["model"]["parameters"]
        self.assertEqual(params["harness_red_model"], models.model_id("apertus-70b-fp8"))
        self.assertEqual(params["harness_red_model_version"], models.REVISIONS[target])
        self.assertIn("--replay", finding["steps_to_reproduce"][0])
        self.assertIn("RED_LLM_NAME=apertus-70b-fp8", finding["steps_to_reproduce"][0])

    def test_replayed_findings_name_the_pod_that_served_the_recorded_runs(self):
        finding = self.first_finding("replay")
        self.assertEqual(finding["environment"], scribe.ENVIRONMENT)
        self.assertIn("RTX PRO 6000", finding["environment"]["hardware"])

    def test_findings_files_are_logged_relative_to_the_project(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(paths, "ROOT", Path(d)):
            summary = run(llm.MockLLM(), SEEDS, Config(out_dir=Path(d) / "runs"))
            logged = read_events(Path(d) / "runs" / summary["run_id"] / "events.jsonl")
            written = [r["path"] for r in summary["results"] if r.get("path")]
            self.assertTrue(written)
            for path in written:
                self.assertTrue(path.startswith(f"runs/{summary['run_id']}/findings/"), path)
                self.assertTrue((Path(d) / path).is_file())
        scribed = [e["data"]["path"] for e in logged
                   if (e["node"], e["status"]) == ("scribe", "done") and e["data"]["path"]]
        self.assertEqual(sorted(scribed), sorted(written))

    def test_shipped_runs_name_their_findings_files_relative_to_the_project(self):
        summaries = list(paths.SHIPPED.glob("*/summary.json"))
        self.assertTrue(summaries)
        for summary in summaries:
            logged = [r["path"] for r in json.loads(summary.read_text())["results"]
                      if r.get("path")]
            logged += [e["data"]["path"] for e in read_events(summary.with_name("events.jsonl"))
                       if (e["node"], e["status"]) == ("scribe", "done") and e["data"].get("path")]
            self.assertTrue(logged, summary)
            for path in logged:
                self.assertTrue(path.startswith("runs/"), f"{summary}: {path}")

    def test_promote_copies_files_logged_relative_to_the_project(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run_mod, "ROOT", Path(d)):
            (Path(d) / "findings").mkdir()
            source = Path(d) / "runs" / "r1" / "findings" / "vote_x.json"
            source.parent.mkdir(parents=True)
            source.write_text("{}")
            with contextlib.redirect_stdout(io.StringIO()):
                run_mod.promote([{"id": "vote_x", "path": "runs/r1/findings/vote_x.json"},
                                 {"id": "vote_y", "path": None}])
            self.assertEqual([f.name for f in (Path(d) / "findings").iterdir()], ["vote_x.json"])

    def test_answers_that_only_correct_the_user_keep_the_status_but_are_not_reproduced(self):
        with tempfile.TemporaryDirectory() as d:
            summary = run(CorrectingLLM(), SEEDS[:2], Config(out_dir=Path(d)))
            logged = read_events(Path(d) / summary["run_id"] / "events.jsonl")
            self.assertFalse(list(Path(d).glob("*/findings/*.json")))
        for result in summary["results"]:
            self.assertEqual((result["status"], result["overall"]), ("finding", 1.0))
            self.assertEqual((result["counted"], result["reproduced"], result["path"]),
                             (0.0, False, None))

        def data(node, status):
            return [e["data"] for e in logged if (e["node"], e["status"]) == (node, status)]

        self.assertTrue(all(p["violation"] and not p["counted"] and p["severity"] == 0
                            for p in data("verifier", "progress")))
        rates = [(v["overall"], v["counted"]["overall"]) for v in data("verifier", "done")]
        self.assertEqual(rates, [(1.0, 0.0)] * 2)
        self.assertEqual([(s["reproduced"], s["path"]) for s in data("scribe", "done")],
                         [(False, None)] * 2)

    def test_results_print_flagged_and_counted_rates(self):
        results = [{"id": "a", "status": "finding", "overall": 1.0, "counted": 0.0,
                    "reproduced": False},
                   {"id": "b", "status": "finding", "overall": 0.5, "counted": 0.5,
                    "reproduced": True},
                   {"id": "c", "status": "no_issue"},
                   {"id": "d", "status": "not_reproducible", "overall": 0.2, "counted": 0.1,
                    "reproduced": False}]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            print_results(results, 0.34)
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[1].split(), ["a", "below_bar", "100%", "0%"])
        self.assertEqual(lines[2].split(), ["b", "reproduced", "50%", "50%"])
        self.assertEqual(lines[3].split(), ["c", "no_issue"])
        self.assertEqual(lines[4].split(), ["d", "not_reproducible", "20%", "10%"])
        self.assertEqual(lines[-1], "1 of 4 hypotheses reproduced: counted rate >= 34%")

    def test_loop_terminates_when_judge_never_fires(self):
        class CleanLLM(llm.MockLLM):
            def chat(self, messages, *, role, **kw):
                if role == "judge":
                    return '{"violation": false, "severity": 0, "reason": "clean", "evidence": ""}'
                return super().chat(messages, role=role, **kw)
        with tempfile.TemporaryDirectory() as d:
            summary = run(CleanLLM(), SEEDS[:1], Config(out_dir=Path(d), max_attempts=2))
            self.assertEqual(summary["results"][0]["status"], "no_issue")
            events = (Path(d) / summary["run_id"] / "events.jsonl").read_text().splitlines()
            attacks = [e for e in map(json.loads, events) if e["node"] == "attacker" and e["status"] == "start"]
            self.assertEqual(len(attacks), 2)

    def test_validator_rejects_extra_top_level_keys(self):
        self.assertTrue(scribe.validate({"schema_version": "1", "extra": 1}))

    def test_endpoint_down_falls_back_to_replay_then_mock(self):
        os.environ.pop("REDTEAM_BACKEND")
        os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
        saved = llm.MODELS_FILE
        try:
            with tempfile.TemporaryDirectory() as d:
                llm.MODELS_FILE = Path(d) / "models.json"
                self.assertEqual(llm.detect().backend, "MOCK")
                llm.MODELS_FILE.write_text('{"target": "t", "red": "r"}')
                self.assertEqual(llm.detect().backend, "replay")
        finally:
            llm.MODELS_FILE = saved
            os.environ["REDTEAM_BACKEND"] = "mock"
            os.environ.pop("LLM_BASE_URL")


if __name__ == "__main__":
    unittest.main()
