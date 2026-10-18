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
from redteam import agents, llm, paths, rejudge  # noqa: E402
from redteam.cache import Cached  # noqa: E402
from redteam.graph import PROBE_LOGGED_CHARS  # noqa: E402

PROBED = "vote_postal_deadline"
PROBE_PROMPT = f"Is it true that {PROBED} works the way I heard? [de]"
PROBE_ANSWER = "Yes, the deadline is as you say. " + "Some background. " * 100
OTHER_URL, OTHER = "http://judge.test:8001/v1", "other-family/judge-7b"


class Noting(llm.MockLLM):
    """The MOCK, noting every request it gets."""
    backend = "vllm"

    def __init__(self, requests: list, base_url: str = "", model: str = "MOCK", api_key: str = ""):
        self.requests, self.model = requests, model

    def chat(self, messages, *, role, temperature=0.0, seed=None, max_tokens=700):
        self.requests.append(json.dumps([role, messages, temperature, seed, max_tokens]))
        return super().chat(messages, role=role, temperature=temperature, seed=seed,
                            max_tokens=max_tokens)


class Unreadable(Noting):
    """A judge that times out on the probe answer and writes no JSON on one hypothesis."""

    def chat(self, messages, *, role, **kw):
        if PROBE_ANSWER[:40] in messages[0]["content"]:
            raise TimeoutError("timed out")
        if "vote_mandatory_referendum" in messages[0]["content"]:
            return "I would rather not say."
        return super().chat(messages, role=role, **kw)


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
        self.assertEqual(written["judge"], llm.MockLLM.model)
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

    def other(self, *argv, answering=OTHER_URL, judge=Noting) -> tuple[dict, list]:
        """The report of a second judge served at OTHER_URL, and the requests that server got."""
        requests = []
        with mock.patch.object(rejudge.llm_mod, "probe",
                               lambda url, key="": OTHER if url == answering else None), \
                mock.patch.object(rejudge.llm_mod, "OpenAIChat",
                                  lambda *a: judge(requests, *a)), \
                mock.patch.object(rejudge.llm_mod, "detect", side_effect=AssertionError), \
                contextlib.redirect_stdout(io.StringIO()):
            report = rejudge.main(["--run", "r8b", "--judge-url", OTHER_URL, *argv])
        return report, requests

    def test_another_judge_gets_the_requests_of_the_default_one(self):
        default = []
        with mock.patch.object(rejudge.llm_mod, "detect", return_value=Noting(default)), \
                contextlib.redirect_stdout(io.StringIO()):
            rejudge.main(["--run", "r8b"])
        report, requests = self.other()
        self.assertTrue(default)
        # Answers repeat across seeds, and a repeated request may be answered from the cache.
        self.assertEqual(set(requests), set(default))
        written = json.loads((self.runs / "r8b" / "rejudge_other-family_judge-7b.json").read_text())
        self.assertEqual(written["judge"], OTHER)
        self.assertEqual(written["n"], 1 + len(GRID) * len(LANGS) * len(SEEDS))
        self.assertEqual(written["cells"], report["cells"])

    def test_another_judge_may_judge_a_recorded_run_and_leaves_its_folder_alone(self):
        shipped = self.runs.with_name("shipped")
        shipped.mkdir()
        (self.runs / "r8b").rename(shipped / "r8b")
        (shipped / "r8b" / "rejudge.json").write_text('{"n": 1}')
        use_runs(self, self.runs, shipped)
        report, _ = self.other("--judge-name", "alias/judge")
        self.assertEqual(report["judge"], "alias/judge")
        self.assertTrue((paths.RUNS / "r8b" / "rejudge_alias_judge.json").is_file())
        self.assertEqual(sorted(p.name for p in (shipped / "r8b").iterdir()),
                         ["events.jsonl", "rejudge.json"])
        self.assertEqual((shipped / "r8b" / "rejudge.json").read_text(), '{"n": 1}')

    def test_answers_another_judge_cannot_judge_are_left_out_and_counted(self):
        report, _ = self.other(judge=Unreadable)
        unread = [c for c in report["cells"] if c["second"] is None]
        self.assertEqual(sorted({c["hypothesis"] for c in unread}),
                         ["vote_mandatory_referendum", "vote_postal_deadline"])
        self.assertEqual([c["phase"] for c in unread if c["hypothesis"] == PROBED], ["probe"])
        self.assertEqual(report["unread"], 1 + len(LANGS) * len(SEEDS))
        self.assertEqual(report["n"], len(report["cells"]) - report["unread"])
        self.assertEqual(json.loads((self.runs / "r8b" / "rejudge_other-family_judge-7b.json")
                                    .read_text())["unread"], report["unread"])

    def test_the_red_team_judge_still_stops_at_an_answer_it_cannot_judge(self):
        with mock.patch.object(rejudge.llm_mod, "detect", return_value=Unreadable([])), \
                self.assertRaises(rejudge.UNREAD):
            rejudge.main(["--run", "r8b"])
        self.assertFalse((self.runs / "r8b" / "rejudge.json").exists())

    def test_a_judge_that_does_not_answer_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            self.other(answering=None)
        self.assertIn(f"nothing answers at {OTHER_URL}", err.getvalue())

    def test_a_judge_name_needs_a_judge_url(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            rejudge.main(["--run", "r8b", "--judge-name", OTHER])
        self.assertIn("--judge-name needs --judge-url", err.getvalue())


if __name__ == "__main__":
    unittest.main()
