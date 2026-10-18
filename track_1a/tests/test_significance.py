"""The tests of redteam.significance, each on a case small enough to check by hand."""
import random
import sys
import unittest
from math import erfc, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import significance as sig  # noqa: E402


class CmhTest(unittest.TestCase):
    def test_two_strata_by_hand(self):
        # Each stratum: E[a] = 3 * 3 / 6 = 1.5, Var = 3^4 / (6^2 * 5) = 0.45, so the deviation is
        # 2 * 0.5 = 1 and the variance 0.9; the odds ratio is (2 * 4/6) / (2 * 1/6) = 4.
        corrected = sig.cmh([(2, 1, 1, 2)] * 2)
        self.assertAlmostEqual(corrected.statistic, 0.5 ** 2 / 0.9)
        self.assertAlmostEqual(corrected.p, erfc(sqrt(0.5 ** 2 / 0.9 / 2)))
        self.assertAlmostEqual(corrected.odds_ratio, 4.0)
        self.assertAlmostEqual(sig.cmh([(2, 1, 1, 2)] * 2, correct=False).statistic, 1 / 0.9)

    def test_matches_the_published_berkeley_admissions_result(self):
        # Admitted and rejected men, then women, in departments A to F; R's mantelhaen.test
        # gives X-squared 1.4269 (corrected), p 0.2323, common odds ratio 0.9047.
        departments = [(512, 313, 89, 19), (353, 207, 17, 8), (120, 205, 202, 391),
                       (138, 279, 131, 244), (53, 138, 94, 299), (22, 351, 24, 317)]
        test = sig.cmh(departments)
        self.assertAlmostEqual(test.statistic, 1.4269, places=4)
        self.assertAlmostEqual(test.p, 0.2323, places=4)
        self.assertAlmostEqual(test.odds_ratio, 0.9047, places=4)
        self.assertAlmostEqual(sig.cmh(departments, correct=False).statistic, 1.5246, places=4)

    def test_strata_without_information_are_skipped(self):
        with_empty = sig.cmh([(1, 0, 0, 0), (2, 1, 1, 2)] * 2)
        self.assertEqual(with_empty[:2], sig.cmh([(2, 1, 1, 2)] * 2)[:2])
        self.assertEqual(sig.cmh([(3, 0, 3, 0)]).p, 1.0)  # every answer counts: nothing to compare

    def test_the_smallest_p_of_three_answers_against_fifteen(self):
        # E[a] = 15 * 15 / 18 = 12.5, Var = 15 * 3 * 15 * 3 / (18^2 * 17) = 0.3676.
        test = sig.cmh([(15, 0, 0, 3)])
        self.assertAlmostEqual(test.statistic, 2.0 ** 2 / (2025 / 5508))
        self.assertAlmostEqual(test.p, 0.000972, places=6)


class ExactTest(unittest.TestCase):
    def test_fisher_of_three_answers_against_fifteen(self):
        # Margins 15 and 3 answers, 15 counted: C(18, 3) = 816 tables. All 15 counted on the first
        # side is 1 of them and the least likely, so p = 1/816 (cmh's chi-square gives 0.000972).
        self.assertEqual(sig.fisher(15, 0, 0, 3), 1 / 816)
        self.assertEqual(sig.fisher(0, 3, 15, 0), 1 / 816)
        # 14 counted: the first side's 14 of 15 weighs C(14,14) C(4,1) = 4 of C(18, 15) = 816.
        self.assertEqual(sig.fisher(14, 1, 0, 3), 4 / 816)
        # 3 against 3 with 3 counted: 0 to 3 counted on the first side weigh 1, 9, 9, 1 of 20.
        # Every table is at most as likely as 2 counted, so p 1; 3 counted gives (1 + 1) / 20.
        self.assertEqual(sig.fisher(2, 1, 1, 2), 1.0)
        self.assertEqual(sig.fisher(3, 0, 0, 3), 2 / 20)

    def test_fisher_floor(self):
        self.assertEqual(sig.fisher_floor(15, 3, 15), 1 / 816)
        self.assertEqual(sig.fisher_floor(15, 3, 14), 4 / 816)
        self.assertEqual(sig.fisher_floor(15, 3, 0), 1.0)  # nothing counted: one possible table

    def test_tarone(self):
        # m = 1: two floors below 0.05, more than 1; m = 2: two below 0.025, not more than 2.
        self.assertEqual(sig.tarone([0.001, 0.001, 0.2, 1.0]), 2)
        self.assertEqual(sig.tarone([1.0, 1.0]), 1)
        self.assertEqual(sig.tarone([]), 0)

    def test_binomial(self):
        self.assertEqual(sig.binomial_p(0, 5), 2 / 32)
        self.assertEqual(sig.binomial_p(1, 10), 2 * 11 / 1024)
        self.assertEqual(sig.binomial_p(5, 10), 1.0)
        self.assertEqual(sig.binomial_p(0, 0), 1.0)

    def test_mcnemar_uses_only_discordant_pairs(self):
        pairs = [(True, False)] * 6 + [(False, True)] + [(True, True)] * 9 + [(False, False)] * 4
        self.assertEqual(sig.mcnemar(pairs), sig.Paired(6, 1, 2 * (1 + 7) / 128))

    def test_sign_test_drops_ties(self):
        self.assertEqual(sig.sign_test([1, -1, 0, 2, 3]), sig.Paired(3, 1, 2 * (1 + 4) / 16))

    def test_holm(self):
        self.assertEqual(sig.holm([0.01, 0.04, 0.03]), [0.03, 0.06, 0.06])
        self.assertEqual(sig.holm([0.6, 0.7]), [1.0, 1.0])
        self.assertEqual(sig.holm([]), [])


class PermutationTest(unittest.TestCase):
    def test_two_strata_of_two(self):
        # Only the arrangement with "a" on the 1 in both strata reaches 2: p is about 1/4.
        strata = [[("a", 1), ("b", 0)], [("a", 1), ("b", 0)]]

        def a_total(arranged):
            return sum(unit for stratum in arranged for label, unit in stratum if label == "a")

        test = sig.permutation_test(strata, a_total, draws=4000)
        self.assertEqual(test.observed, 2)
        self.assertAlmostEqual(test.p, 0.25, delta=0.02)
        self.assertAlmostEqual(test.expected, 1.0, delta=0.05)
        self.assertEqual(sig.permutation_test(strata, a_total, draws=4000), test)  # fixed seed

    def test_labels_stay_in_their_stratum(self):
        strata = [[("a", 1), ("a", 2)], [("b", 3), ("c", 4)]]
        seen = set()
        sig.permutation_test(strata, lambda s: seen.add(tuple(sorted(l for l, _ in s[0]))) or 0,
                             draws=50)
        self.assertEqual(seen, {("a", "a")})

    def test_rate_variance(self):
        # en 1 of 6 and rm 5 of 6: mean 1/2, each 1/3 away from it.
        strata = [[("en", (0, 3)), ("rm", (3, 3))], [("en", (1, 3)), ("rm", (2, 3))]]
        self.assertAlmostEqual(sig.rate_variance(strata), 1 / 9)

    def test_split_strata(self):
        whole = [[("en", (3, 3)), ("rm", (0, 3))], [("en", (2, 3)), ("rm", (0, 3))]]
        self.assertEqual(sig.split_strata(whole), 1)
        single = [[("en", (1, 1))] * 3 + [("de", (1, 1)), ("de", (0, 1))] + [("rm", (0, 1))] * 3]
        self.assertEqual(sig.split_strata(single), 1)

    def test_paired_shift(self):
        strata = [[("first", 2), ("second", 5)], [("first", 4), ("second", 3)]]
        self.assertEqual(sig.paired_shift(strata), 2)
        # Both strata change by 3, so flipping either sign gives 0: p = 2 of 4 arrangements.
        test = sig.permutation_test([[("first", 0), ("second", 3)]] * 2, sig.paired_shift, 4000)
        self.assertAlmostEqual(test.p, 0.5, delta=0.03)


class IccTest(unittest.TestCase):
    def test_by_hand(self):
        self.assertEqual(sig.icc([[1, 1], [0, 0]]), 1.0)
        self.assertEqual(sig.icc([[1, 0], [1, 0]]), -1.0)
        self.assertEqual(sig.icc([[1, 1], [1, 1]]), 0.0)
        # Unequal sizes: MSB 8/15, MSW 2/9, n0 12/5, so (8/15 - 2/9) / (8/15 + 7/5 * 2/9) = 7/19.
        self.assertAlmostEqual(sig.icc([[1, 1, 0], [0, 0]]), 7 / 19)

    def test_nothing_to_compare_gives_zero(self):
        self.assertEqual(sig.icc([[1, 0]]), 0.0)  # one group
        self.assertEqual(sig.icc([[1], [0]]), 0.0)  # groups of one

    def test_beta_rates_give_the_correlation_they_are_drawn_with(self):
        rng = random.Random(3)
        groups = []
        for _ in range(4000):
            rate = sig.hypothesis_rate(rng, 0.3, 0.3)
            groups.append([int(rng.random() < rate) for _ in range(2)])
        self.assertAlmostEqual(sig.icc(groups), 0.3, delta=0.05)
        self.assertEqual(sig.hypothesis_rate(rng, 0.3, 0.0), 0.3)

    def test_full_correlation_draws_all_or_nothing(self):
        rng = random.Random(3)
        rates = [sig.hypothesis_rate(rng, 0.3, 1.0) for _ in range(4000)]
        self.assertEqual(set(rates), {0.0, 1.0})
        self.assertAlmostEqual(sum(rates) / len(rates), 0.3, delta=0.03)


class PowerTest(unittest.TestCase):
    # English at 25% in 3 answers against 15 that always count: by Fisher significant only when
    # English has 0 or 1 counted (p 1/816 and 16/816; 2 gives 136/816 = 0.17), so power is
    # 27/64 + 27/64 = 0.84.
    DESIGN = sig.Design(1, (3, 15), 0.0, 0.25)

    def test_shifted_rate(self):
        self.assertAlmostEqual(sig.shifted_rate(0.25, 3.0), 0.5)
        self.assertEqual(sig.shifted_rate(0.25, 1.0), 0.25)

    def test_pooled_rate(self):
        # No spread between hypotheses: every one sits at the base, so the pooled rate is the
        # shifted base, 0.3 * 3 / (0.9 + 0.7) = 0.5625.
        self.assertAlmostEqual(sig.pooled_rate(sig.Design(5, (3, 3), 0.0, 0.3), 3.0, 10), 0.5625)
        # Full correlation: hypotheses at 0 or 1, which no odds ratio moves, so it stays near 0.3.
        pooled = sig.pooled_rate(sig.Design(5, (3, 3), 1.0, 0.3), 3.0, 20_000)
        self.assertAlmostEqual(pooled, 0.3, delta=0.01)

    def test_power_against_a_near_certain_difference(self):
        self.assertAlmostEqual(sig.power(self.DESIGN, 1e4), 0.84, delta=0.03)

    def test_no_difference_is_rarely_found(self):
        self.assertLess(sig.power(sig.Design(20, (3, 3), 0.3, 0.3), 1.0, draws=500), 0.07)

    def test_mde(self):
        self.assertIsNone(sig.mde(self.DESIGN, target=0.9, draws=500))
        ratio = sig.mde(self.DESIGN, draws=500)
        self.assertGreaterEqual(sig.power(self.DESIGN, ratio, draws=500), 0.8)
        self.assertLess(sig.power(self.DESIGN, ratio / 1.5, draws=500), 0.8)


if __name__ == "__main__":
    unittest.main()
