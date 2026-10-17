import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import review  # noqa: E402

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
    def test_pairs_answer_and_balances_classes(self):
        events = [{"hypothesis": "h", "node": "mutator", "status": "done",
                   "data": {"prompts": {"de": "P-de", "fr": "P-fr"}}}]
        for k in range(6):
            lang = "de" if k % 2 else "fr"
            events += [{"hypothesis": "h", "node": "target", "status": "done",
                        "data": {"lang": lang, "answer": f"A{k}"}},
                       {"hypothesis": "h", "node": "judge", "status": "done",
                        "data": {"lang": lang, "violation": k < 2, "reason": f"R{k}"}}]
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "run1").mkdir()
            (Path(d) / "run1" / "events.jsonl").write_text("\n".join(map(json.dumps, events)))
            with mock.patch.object(review, "RUNS", Path(d)):
                picked = review.sample("run1", n=4)
        self.assertEqual(sum(it["judge_violation"] for it in picked), 2)
        for it in picked:
            k = it["judge_reason"][1:]
            self.assertEqual(it["answer"], "A" + k)
            self.assertEqual(it["prompt"], "P-" + it["lang"])


if __name__ == "__main__":
    unittest.main()
