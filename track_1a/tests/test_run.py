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

from redteam import llm, run as run_mod  # noqa: E402

BANK = [h["id"] for h in run_mod.load_hypotheses()]


class ReplayTest(unittest.TestCase):
    """`make run` replays the recorded run, even after hypotheses were added to the banks."""

    def given(self, *argv) -> list[str]:
        """The hypotheses `python -m redteam.run --replay ARGV` hands to the graph."""
        given = []

        def graph(client, seeds, cfg):
            given.extend(s["id"] for s in seeds)
            return {"results": [], "run_id": "r"}

        with mock.patch.dict(os.environ), mock.patch.object(run_mod, "run", graph), \
                contextlib.redirect_stdout(io.StringIO()):
            run_mod.main(["--replay", *argv])
        return given

    def use_models(self, **models):
        path = Path(self.enterContext(tempfile.TemporaryDirectory())) / "models.json"
        path.write_text(json.dumps({"target": "t", "red": "r", **models}))
        self.enterContext(mock.patch.object(llm, "MODELS_FILE", path))

    def test_replays_exactly_the_hypotheses_of_the_recorded_run(self):
        recorded = json.loads(llm.MODELS_FILE.read_text())["hypotheses"]
        given = self.given()
        self.assertEqual(sorted(given), sorted(recorded))
        self.assertEqual(given, [h for h in BANK if h in recorded])  # in the order of the banks

    def test_only_runs_the_hypotheses_asked_for_recorded_or_not(self):
        self.use_models(hypotheses=[BANK[0]])
        self.assertEqual(self.given("--only", BANK[1]), [BANK[1]])

    def test_a_models_file_without_hypotheses_replays_the_whole_bank(self):
        self.use_models()  # as the first live run writes it
        self.assertEqual(self.given(), BANK)


if __name__ == "__main__":
    unittest.main()
