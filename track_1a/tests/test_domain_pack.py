"""Hypothesis packs for other domains (examples/<domain>/): each one has the format of the built-in
banks, loading it leaves the built-in banks and the replay of the recorded run as they were, and the
coding pack runs end to end on the MOCK backend."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS.parent / "src"), str(TESTS)]

import test_hypotheses  # noqa: E402
from redteam import llm, run as run_mod  # noqa: E402

EXAMPLES = TESTS.parent / "examples"
CODING = EXAMPLES / "coding"
FIELDS = {"id", "title", "topic_area", "domain", "hypothesis", "reference", "sources", "harm"}
EXTRA = {"id": "extra_claim", "title": "Extra claim", "topic_area": "t", "domain": "extra",
         "hypothesis": "h", "reference": "r", "sources": [], "harm": "x"}
NEEDS_EXAMPLES = unittest.skipUnless(CODING.is_dir(), "examples/ is not in the Docker image")


def added_by(pack: Path) -> list[dict]:
    """The hypotheses a pack adds to the built-in banks."""
    return run_mod.load_hypotheses([str(pack)])[len(run_mod.load_hypotheses([])):]


def isolate(test, **env) -> Path:
    """An environment that names no pack, as `make run` has, and a folder for the test."""
    test.enterContext(mock.patch.dict(os.environ, env))
    os.environ.pop(run_mod.BANKS, None)
    return Path(test.enterContext(tempfile.TemporaryDirectory()))


@NEEDS_EXAMPLES
class PackFormatTest(unittest.TestCase):
    def setUp(self):
        isolate(self)
        self.packs = sorted(p for p in EXAMPLES.iterdir() if any(p.glob("*.json")))

    def test_every_hypothesis_has_the_fields_of_the_built_in_banks(self):
        topics = {h["topic_area"] for h in run_mod.load_hypotheses()}
        for pack in self.packs:
            for h in added_by(pack):
                with self.subTest(pack=pack.name, hypothesis=h.get("id")):
                    self.assertEqual(set(h), FIELDS)
                    text = [h[k] for k in FIELDS - {"sources"}]
                    self.assertTrue(all(isinstance(t, str) and t.strip() for t in text))
                    self.assertIn(h["topic_area"], topics)
                    self.assertTrue(h["sources"])
                    self.assertTrue(all(s.startswith("https://") for s in h["sources"]))

    def test_titles_pass_the_title_test_with_the_pack_loaded(self):
        title_test = test_hypotheses.TitleTest()
        for pack in self.packs:
            with self.subTest(pack=pack.name):
                os.environ[run_mod.BANKS] = str(pack)
                title_test.test_every_hypothesis_has_a_short_unique_title()

    def test_the_coding_pack_is_one_domain(self):
        self.assertEqual({h["domain"] for h in added_by(CODING)}, {"coding"})


class DefaultLoadTest(unittest.TestCase):
    """Without REDTEAM_BANKS the banks, and so every cache key, are what they were."""

    def setUp(self):
        self.bank = isolate(self) / "bank.json"
        self.bank.write_text(json.dumps([EXTRA]))

    def test_the_default_load_is_the_built_in_banks_in_file_order(self):
        files = sorted(run_mod.HYPOTHESES.glob("*.json"))
        self.assertEqual(run_mod.load_hypotheses(),
                         [h for f in files for h in json.loads(f.read_text())])

    def test_an_extra_bank_only_adds_hypotheses_after_the_built_in_ones(self):
        builtin = run_mod.load_hypotheses()
        os.environ[run_mod.BANKS] = str(self.bank)
        self.assertEqual(run_mod.load_hypotheses(), [*builtin, EXTRA])
        self.assertEqual(run_mod.load_hypotheses([str(self.bank.parent)]), [*builtin, EXTRA])

    def test_a_relative_bank_is_read_from_track_1a(self):
        relative = os.path.relpath(self.bank, run_mod.ROOT)
        self.enterContext(contextlib.chdir(self.bank.parent))
        self.assertEqual(run_mod.load_hypotheses([relative])[-1], EXTRA)

    def test_a_repeated_id_is_refused_within_a_bank_and_across_banks(self):
        for repeated in ([EXTRA, EXTRA], run_mod.load_hypotheses()[:1]):
            self.bank.write_text(json.dumps(repeated))
            with self.subTest(id=repeated[0]["id"]), self.assertRaisesRegex(
                    ValueError, "repeated hypothesis ids: " + repeated[0]["id"]):
                run_mod.load_hypotheses([str(self.bank)])

    def test_a_bank_that_does_not_parse_is_named(self):
        self.bank.write_text("[{")
        with self.assertRaisesRegex(ValueError, f"{self.bank} is not valid JSON"):
            run_mod.load_hypotheses([str(self.bank)])

    def test_the_replay_of_the_recorded_run_ignores_extra_banks(self):
        given = []

        def graph(client, seeds, cfg):
            given.extend(s["id"] for s in seeds)
            return {"results": [], "run_id": "r"}

        os.environ[run_mod.BANKS] = str(self.bank)
        with mock.patch.object(run_mod, "run", graph), contextlib.redirect_stdout(io.StringIO()):
            run_mod.main(["--replay"])
        recorded = json.loads(llm.MODELS_FILE.read_text())["hypotheses"]
        self.assertEqual(sorted(given), sorted(recorded))


@NEEDS_EXAMPLES
class MockRunTest(unittest.TestCase):
    """The coding pack has no recorded run; on the MOCK backend it still runs every step."""

    def setUp(self):
        self.runs = isolate(self, REDTEAM_BACKEND="mock")
        self.enterContext(mock.patch.object(run_mod, "RUNS", self.runs))

    def run_pack(self, *argv, pack="examples/coding") -> tuple[dict, str]:
        os.environ[run_mod.BANKS] = pack
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            summary = run_mod.main(["--domain", "coding", *argv])
        return summary, out.getvalue()

    def test_a_mock_run_writes_its_events_marked_as_mock(self):
        summary, printed = self.run_pack("--langs", "en,gsw,rm", "--parallel", "2")
        coding = [h["id"] for h in added_by(CODING)]
        self.assertIn("MOCK: results are NOT findings", printed)
        self.assertEqual(summary["backend"], "MOCK")
        self.assertEqual([r["id"] for r in summary["results"]], coding)
        self.assertNotIn("error", {r["status"] for r in summary["results"]})

        run_dir = self.runs / summary["run_id"]
        events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
        self.assertEqual({(e["backend"], e["model"]) for e in events}, {("MOCK", "MOCK-no-model")})
        self.assertEqual(events[0]["data"]["hypotheses"], coding)
        self.assertEqual(events[-1]["status"], "end")
        findings = [json.loads(f.read_text()) for f in (run_dir / "findings").glob("*.json")]
        self.assertTrue(findings)
        self.assertTrue(all(f["issue_title"].startswith("[MOCK]") for f in findings))

    def test_mistakes_stop_before_the_run(self):
        coding = "examples/coding"
        mistakes = {"unknown language": (["--langs", "en,xx"], coding),
                    "unknown id": (["--only", "code_sql_equals_null", "code_sql_null"], coding),
                    "unknown domain": (["--domain", "codng"], coding),
                    "pack not named": ([], ""),
                    "pack not found": ([], "examples/codng")}
        for mistake, (argv, pack) in mistakes.items():
            with self.subTest(mistake), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    self.run_pack(*argv, pack=pack)
        self.assertEqual(list(self.runs.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
