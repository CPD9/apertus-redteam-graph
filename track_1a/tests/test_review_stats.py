import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import review_stats  # noqa: E402
from redteam.calibration import rogan_gladen  # noqa: E402

POPULATION = Counter({("x", True): 9, ("x", False): 6, ("y", True): 4, ("y", False): 11})


def labels(lang: str, counted: bool, yes: int, no: int, start: int = 0) -> list[dict]:
    """yes + no answers of one stratum, each labelled once, each from its own hypothesis."""
    return [{"id": f"{lang}{counted}{start + i}", "lang": lang, "judge_violation": counted,
             "human_violation": i < yes, "hypothesis": f"h{start + i}"} for i in range(yes + no)]


def width(figure: dict) -> float:
    return figure["ci95"][1] - figure["ci95"][0]


class AccuracyTest(unittest.TestCase):
    def test_a_languages_corrected_rate_is_rogan_gladen_with_its_own_se_and_sp(self):
        rows = labels("x", True, 4, 1) + labels("x", False, 3, 7) + labels("y", True, 1, 1) + \
            labels("y", False, 0, 4)
        rates = review_stats.accuracy(rows, POPULATION)["rates"]
        tp, fp, fn, tn = 9 * 0.8, 9 * 0.2, 6 * 0.3, 6 * 0.7
        self.assertAlmostEqual(rates["x"]["corrected"]["estimate"],
                               round(rogan_gladen(9 / 15, tp / (tp + fn), tn / (tn + fp)), 3))
        self.assertEqual(rates["y"]["corrected"]["estimate"], round(4 * 0.5 / 15, 3))
        self.assertEqual(rates["all"]["corrected"]["estimate"], round((7.2 + 1.8 + 2) / 30, 3))

    def test_intervals_narrow_as_labels_grow(self):
        few = labels("x", True, 1, 1) + labels("x", False, 1, 1)
        many = labels("x", True, 5, 5) + labels("x", False, 5, 5)
        small = Counter({k: n for k, n in POPULATION.items() if k[0] == "x"})
        a, b = review_stats.accuracy(few, small), review_stats.accuracy(many, small)
        for key in ("sensitivity", "specificity"):
            self.assertGreater(width(a[key]), width(b[key]), key)
        self.assertGreater(width(a["rates"]["x"]["corrected"]), width(b["rates"]["x"]["corrected"]))

    def test_labels_that_all_agree_still_leave_room(self):
        rows = labels("x", True, 3, 0) + labels("x", False, 0, 3)
        acc = review_stats.accuracy(rows, Counter({("x", True): 9, ("x", False): 6}))
        self.assertEqual(acc["sensitivity"]["estimate"], 1.0)
        self.assertEqual(acc["sensitivity"]["ci95"][1], 1.0)
        self.assertLess(acc["sensitivity"]["ci95"][0], 0.9)

    def test_an_answer_two_people_labelled_counts_once(self):
        rows = labels("x", True, 1, 0) + [{**labels("x", True, 0, 1)[0], "id": "xTrue0"}]
        self.assertEqual(review_stats.stratum_shares(rows), {("x", True): [0.5]})


class TallyTest(unittest.TestCase):
    def test_raw_agreement_and_kappa_come_with_intervals(self):
        triples = [(True, True, f"h{i}") for i in range(6)] + \
            [(False, False, f"h{i}") for i in range(6, 10)] + \
            [(True, False, "h10"), (False, True, "h11")]
        t = review_stats.tally(triples)
        self.assertEqual((t["n"], t["agree"], t["raw_agreement"]), (12, 10, 0.833))
        self.assertLess(t["ci95"][0], 0.833)
        self.assertLess(t["kappa_ci95"][0], t["kappa"])
        self.assertLessEqual(t["kappa"], t["kappa_ci95"][1])

    def test_nothing_to_tally(self):
        self.assertEqual(review_stats.tally([]), {"n": 0, "agree": 0, "raw_agreement": None,
                                                  "ci95": None, "kappa": None, "kappa_ci95": None})


if __name__ == "__main__":
    unittest.main()
