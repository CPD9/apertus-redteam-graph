import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["REDTEAM_BACKEND"] = "mock"

from redteam import agents, llm, scribe  # noqa: E402
from redteam.graph import Config, run  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

SEEDS = load_hypotheses()[:5]


class GraphTest(unittest.TestCase):
    def test_mock_run_produces_schema_valid_findings(self):
        with tempfile.TemporaryDirectory() as d:
            summary = run(llm.MockLLM(), SEEDS, Config(out_dir=Path(d)))
            self.assertEqual(summary["backend"], "MOCK")
            self.assertEqual(len(summary["results"]), len(SEEDS))
            self.assertFalse([r for r in summary["results"] if r["status"] == "error"])
            files = list(Path(d).glob("*/findings/*.json"))
            self.assertGreaterEqual(len(files), 1)
            for f in files:
                finding = json.loads(f.read_text())
                self.assertEqual(scribe.validate(finding), [], f.name)
                self.assertTrue(finding["issue_title"].startswith("[MOCK]"))

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

    def test_parse_json_handles_prose_and_fences(self):
        self.assertEqual(agents.parse_json('Sure!\n```json\n{"a": 1}\n```'), {"a": 1})

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
