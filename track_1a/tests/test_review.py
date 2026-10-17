import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import TARGET, Stub, use_runs  # noqa: E402
from redteam import agents, review  # noqa: E402
from redteam.cache import Cached  # noqa: E402
from redteam.graph import PROBE_LOGGED_CHARS  # noqa: E402

ITEM = {"id": "r:1", "run_id": "r", "hypothesis": "h", "lang": "de", "reference": "ref",
        "prompt": "p", "answer": "a", "judge_violation": True, "judge_reason": "x"}


class KappaTest(unittest.TestCase):
    def test_perfect_agreement(self):
        self.assertEqual(review.cohen_kappa([(True, True), (False, False), (True, True)]), 1.0)

    def test_hand_computed(self):
        # 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no: po = .7, pe = .5*.6 + .5*.4 = .5, kappa = .4
        pairs = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 10 + [(False, False)] * 15
        self.assertAlmostEqual(review.cohen_kappa(pairs), 0.4)

    def test_undefined(self):
        self.assertIsNone(review.cohen_kappa([]))
        self.assertIsNone(review.cohen_kappa([(False, False)] * 3))


class LabelTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = Path(d.name) / "judge_cases.jsonl"
        patcher = mock.patch.object(review, "LABELS", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_duplicate_id_is_skipped(self):
        self.assertTrue(review.save_label("r:1", False, "first", item=ITEM))
        self.assertFalse(review.save_label("r:1", True, "second", item=ITEM))
        rows = [json.loads(l) for l in self.path.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["human_violation"], rows[0]["note"]), (False, "first"))

    def test_agreement_ignores_cases_without_judge_verdict(self):
        review.save_label("r:1", True, item=ITEM)
        review.save_label("seed:1", False, item={**ITEM, "id": "seed:1", "judge_violation": None})
        self.assertEqual(review.agreement(), {"n": 1, "raw_agreement": 1.0, "kappa": None})


class SampleTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, self.shipped = Path(d.name) / "runs", Path(d.name) / "data-runs"
        use_runs(self, self.runs, self.shipped)

    @staticmethod
    def write(root: Path, run_id: str) -> None:
        events = [{"hypothesis": "h", "node": "mutator", "status": "done",
                   "data": {"prompts": {"de": "P-de", "fr": "P-fr"}}}]
        for k in range(6):
            lang = "de" if k % 2 else "fr"
            events += [{"hypothesis": "h", "node": "target", "status": "done",
                        "data": {"lang": lang, "answer": f"A{k}"}},
                       {"hypothesis": "h", "node": "judge", "status": "done",
                        "data": {"lang": lang, "violation": k < 2, "reason": f"R{k}"}}]
        (root / run_id).mkdir(parents=True)
        (root / run_id / "events.jsonl").write_text("\n".join(map(json.dumps, events)))

    def test_pairs_answer_and_balances_classes(self):
        self.write(self.runs, "run1")
        picked = review.sample("run1", n=4)
        self.assertEqual(sum(it["judge_violation"] for it in picked), 2)
        for it in picked:
            k = it["judge_reason"][1:]
            self.assertEqual(it["answer"], "A" + k)
            self.assertEqual(it["prompt"], "P-" + it["lang"])

    def test_recorded_runs_open_from_data_runs(self):
        self.write(self.shipped, "run1")
        picked = review.sample("run1", n=4)
        self.assertEqual({it["run_id"] for it in picked}, {"run1"})
        item = review.find(picked[0]["id"])
        self.assertEqual(item, picked[0])

    def test_a_line_cut_off_mid_write_is_skipped(self):
        self.write(self.runs, "run1")
        before = review.items("run1")
        log = self.runs / "run1" / "events.jsonl"
        log.write_text(log.read_text() + '\n{"hypothesis": "h", "node": "jud')
        self.assertEqual(review.items("run1"), before)
        self.assertEqual(len(review.sample("run1", n=4)), 4)

    def test_unknown_runs_and_a_missing_latest_are_errors(self):
        self.write(self.shipped, "run1")
        for run_id in ("latest", "nope", "../run1"):
            with self.assertRaises(ValueError):
                review.sample(run_id)


class FullAnswerTest(unittest.TestCase):
    """The event log keeps only the start of a probe answer; reviewers see all of it."""

    SYSTEM = "Check the premise first."
    ANSWER = "Yes, the deadline is as you say. " + "Some background. " * 100

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, self.cache = Path(d.name) / "runs", Path(d.name) / "cache"
        use_runs(self, self.runs)
        patcher = mock.patch.object(review, "CACHE_DIR", self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        events = [{"hypothesis": None, "node": "graph", "status": "start", "model": TARGET,
                   "data": {"system": self.SYSTEM}},
                  {"hypothesis": "h", "node": "mutator", "status": "done",
                   "data": {"prompts": {"de": "P-de"}}},
                  {"hypothesis": "h", "node": "target", "status": "done",
                   "data": {"lang": "de", "answer": self.ANSWER[:PROBE_LOGGED_CHARS]}},
                  {"hypothesis": "h", "node": "judge", "status": "done",
                   "data": {"lang": "de", "violation": True, "reason": "agrees"}}]
        (self.runs / "run1").mkdir(parents=True)
        (self.runs / "run1" / "events.jsonl").write_text("\n".join(map(json.dumps, events)))

    def test_a_cut_answer_is_replayed_in_full(self):
        # The probe asks once, at temperature 0 with seed 0 and the run's system prompt.
        agents.target(Cached(Stub({("P-de", 0): self.ANSWER}), TARGET, root=self.cache),
                      "P-de", 0, 0.0, self.SYSTEM)
        [item] = review.sample("run1", n=1)
        self.assertEqual(item["answer"], self.ANSWER)
        self.assertEqual(review.find(item["id"]), item)
        self.assertEqual(item["id"], "run1:3")

    def test_an_answer_missing_from_the_cache_keeps_the_logged_start_marked_as_cut(self):
        [item] = review.sample("run1", n=1)
        self.assertTrue(item["answer"].startswith(self.ANSWER[:PROBE_LOGGED_CHARS]))
        self.assertTrue(item["answer"].endswith(
            f"[cut: the event log keeps {PROBE_LOGGED_CHARS} characters]"))


if __name__ == "__main__":
    unittest.main()
