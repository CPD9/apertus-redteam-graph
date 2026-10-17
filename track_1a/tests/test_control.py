import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ["REDTEAM_BACKEND"] = "mock"

from redteam import control, llm  # noqa: E402
from redteam.graph import Config, run  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402


class ControlTest(unittest.TestCase):
    def test_control_compares_premise_and_neutral_rates(self):
        hyps = load_hypotheses()[:3]
        with tempfile.TemporaryDirectory() as d:
            summary = run(llm.MockLLM(), hyps, Config(out_dir=Path(d)))
            control.RUNS = Path(d)
            control.load_hypotheses = lambda: hyps
            control.main(["--run", summary["run_id"]])
            rows = (Path(d) / summary["run_id"] / "control.json").read_text()
        findings = [r for r in summary["results"] if r["status"] == "finding"]
        self.assertEqual(rows.count('"neutral_rate"'), len(findings))


if __name__ == "__main__":
    unittest.main()
