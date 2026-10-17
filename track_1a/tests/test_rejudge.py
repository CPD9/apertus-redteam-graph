import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import (GRID, LANGS, SEEDS, TARGET, Stub, answer, event, use_runs,  # noqa: E402
                     write_run)
from redteam import agents, llm, rejudge  # noqa: E402
from redteam.cache import Cached  # noqa: E402
from redteam.graph import PROBE_LOGGED_CHARS  # noqa: E402

PROBED = "vote_postal_deadline"
PROBE_PROMPT = f"Is it true that {PROBED} works the way I heard? [de]"
PROBE_ANSWER = "Yes, the deadline is as you say. " + "Some background. " * 100


class RejudgeTest(unittest.TestCase):
    """The run of tests/helpers.py, plus one probe-phase answer before its verification."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, self.cache = Path(d.name) / "runs", Path(d.name) / "cache"
        write_run(self.runs, self.cache, "r8b")
        # The probe phase asks once, at temperature 0 with seed 0, and logs the start of it.
        agents.target(Cached(Stub({(PROBE_PROMPT, 0): PROBE_ANSWER}), TARGET, root=self.cache),
                      PROBE_PROMPT, 0, 0.0)
        log = self.runs / "r8b" / "events.jsonl"
        events = [json.loads(line) for line in log.read_text().splitlines()]
        at = 1 + next(i for i, e in enumerate(events)
                      if (e["hypothesis"], e["node"]) == (PROBED, "mutator"))
        events[at:at] = [event("r8b", "vllm", PROBED, "target", "done", lang="de",
                               answer=PROBE_ANSWER[:PROBE_LOGGED_CHARS]),
                         event("r8b", "vllm", PROBED, "judge", "done", lang="de", violation=True)]
        log.write_text("".join(json.dumps(e) + "\n" for e in events))
        use_runs(self, self.runs)
        patcher = mock.patch.object(rejudge, "CACHE_DIR", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_every_answer_is_judged_in_full(self):
        cells = rejudge.judged_cells(self.runs / "r8b", self.cache)
        self.assertEqual(len(cells), 1 + len(GRID) * len(LANGS) * len(SEEDS))
        probes = [c for c in cells if c["phase"] == "probe"]
        self.assertEqual([(c["hypothesis"], c["answer"], c["first"]) for c in probes],
                         [(PROBED, PROBE_ANSWER, True)])
        referendum = [c for c in cells if c["hypothesis"] == "vote_mandatory_referendum"]
        self.assertEqual({c["answer"] for c in referendum},
                         {answer("vote_mandatory_referendum", "w")})
        self.assertGreater(len(referendum[0]["answer"]), 3000)

    def test_report_pairs_both_judges_on_every_answer(self):
        with mock.patch.object(rejudge.llm_mod, "detect", return_value=llm.MockLLM()), \
                contextlib.redirect_stdout(io.StringIO()):
            report = rejudge.main(["--run", "r8b"])
        written = json.loads((self.runs / "r8b" / "rejudge.json").read_text())
        self.assertEqual(written["n"], report["n"])
        self.assertEqual(report["n"], 1 + len(GRID) * len(LANGS) * len(SEEDS))
        self.assertTrue(all(c["second"] is False for c in report["cells"]))

    def test_a_recorded_run_in_data_runs_keeps_its_rejudge(self):
        shipped = self.runs.with_name("shipped")
        shipped.mkdir()
        (self.runs / "r8b").rename(shipped / "r8b")
        (shipped / "r8b" / "rejudge.json").write_text('{"n": 1}')
        use_runs(self, self.runs, shipped)
        with mock.patch.object(rejudge.llm_mod, "detect", side_effect=AssertionError), \
                contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            rejudge.main(["--run", "r8b"])
        self.assertIn("is a recorded run", err.getvalue())
        self.assertEqual((shipped / "r8b" / "rejudge.json").read_text(), '{"n": 1}')
        self.assertFalse((self.runs / "r8b").exists())

    def test_answers_missing_from_the_cache_are_a_usage_error(self):
        with mock.patch.object(rejudge, "CACHE_DIR", self.runs / "no-cache"), \
                contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            rejudge.main(["--run", "r8b"])
        self.assertIn("not in cache", err.getvalue())


if __name__ == "__main__":
    unittest.main()
