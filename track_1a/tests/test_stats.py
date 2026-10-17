import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.stats import cluster_bootstrap, wilson  # noqa: E402

DIALECTS = ["ag", "be", "lu", "zh"]
SENTENCES = [str(i) for i in range(10)]


class ClusterBootstrapTest(unittest.TestCase):
    def test_constant_values_have_no_spread(self):
        values = {(d, s): 0.25 for d in DIALECTS for s in SENTENCES}
        self.assertEqual(cluster_bootstrap(values), (0.25, 0.25))

    def test_the_seed_is_fixed(self):
        values = {(d, s): float((i + j) % 3 == 0) for i, d in enumerate(DIALECTS)
                  for j, s in enumerate(SENTENCES)}
        low, high = cluster_bootstrap(values)
        self.assertEqual(cluster_bootstrap(values), (low, high))
        self.assertLessEqual(low, sum(values.values()) / len(values))
        self.assertGreaterEqual(high, sum(values.values()) / len(values))

    def test_clustered_values_get_a_wider_interval_than_independent_ones(self):
        # Half the dialects get everything wrong: 40 answers, but only 4 independent speakers.
        values = {(d, s): float(d in ("ag", "be")) for d in DIALECTS for s in SENTENCES}
        low, high = cluster_bootstrap(values)
        self.assertLessEqual(low, 0.5)
        self.assertGreaterEqual(high, 0.5)
        wilson_low, wilson_high = wilson(20, 40)
        self.assertGreater(high - low, wilson_high - wilson_low)

    def test_sentences_count_as_clusters_too(self):
        values = {(d, s): float(s in SENTENCES[:5]) for d in DIALECTS for s in SENTENCES}
        low, high = cluster_bootstrap(values)
        self.assertLess(low, 0.4)
        self.assertGreater(high, 0.6)


if __name__ == "__main__":
    unittest.main()
