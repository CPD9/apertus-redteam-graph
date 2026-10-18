import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import use_runs  # noqa: E402
from redteam import paths  # noqa: E402
from redteam.events import EventLog, first_event, read_events  # noqa: E402


class RunDirTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.local, self.shipped = Path(d.name) / "runs", Path(d.name) / "data" / "runs"
        use_runs(self, self.local, self.shipped)

    def make(self, root: Path, run_id: str) -> Path:
        (root / run_id).mkdir(parents=True)
        (root / run_id / "events.jsonl").write_text("{}\n")
        return root / run_id

    def test_a_local_run_comes_before_the_shipped_copy(self):
        shipped = self.make(self.shipped, "r1")
        self.assertEqual(paths.run_dir("r1"), shipped)
        local = self.make(self.local, "r1")
        self.assertEqual(paths.run_dir("r1"), local)

    def test_latest_names_the_newest_local_run(self):
        self.assertIsNone(paths.run_dir("latest"))
        run = self.make(self.local, "r2")
        (self.local / "latest").write_text("r2\n")
        self.assertEqual(paths.run_dir("latest"), run)

    def test_folders_without_a_log_and_unsafe_ids_are_not_runs(self):
        (self.local / "speech").mkdir(parents=True)
        self.make(self.shipped, "r1")
        for run_id in ("speech", "nope", "..", "../runs/r1", "", "r1/"):
            self.assertIsNone(paths.run_dir(run_id), run_id)

    def test_every_run_is_listed_once(self):
        self.make(self.shipped, "r1")
        self.make(self.shipped, "r2")
        self.make(self.local, "r2")
        self.make(self.local, "r3")
        self.assertEqual(paths.run_dirs(), [self.shipped / "r1", self.local / "r2",
                                            self.local / "r3"])


class EventsTest(unittest.TestCase):
    def test_reader_skips_a_line_that_is_still_being_written(self):
        with tempfile.TemporaryDirectory() as d:
            log = EventLog(Path(d) / "r", "r", "MOCK", "m")
            log("graph", "start", {"langs": ["en"]})
            log("attacker", "start", {"attempt": 1}, "h")
            with log.path.open("a") as f:
                f.write('{"t": 1, "run_id": "r", "hyp')
            events = read_events(log.path)
            self.assertEqual([(e["node"], e["hypothesis"]) for e in events],
                             [("graph", None), ("attacker", "h")])
            self.assertEqual(first_event(log.path)["data"], {"langs": ["en"]})

    def test_first_event_of_an_empty_log(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "events.jsonl"
            path.write_text("")
            self.assertEqual(first_event(path), {})
            self.assertEqual(read_events(path), [])
            path.write_text(json.dumps({"node": "graph"}))
            self.assertEqual(first_event(path), {"node": "graph"})


if __name__ == "__main__":
    unittest.main()
