"""Judge calibration against a reference: Se and Sp with Wilson and cluster intervals, the
Rogan-Gladen correction and its bootstraps on hand-worked cases; the report's reference, strata,
misses and speech agreement on written answers and clips; and the recorded runs."""
import json
import sys
import unittest
from collections import Counter
from math import isclose
from pathlib import Path
from statistics import mean

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src")]

import report_calibration as rc  # noqa: E402
import report_scorer as rs  # noqa: E402
from redteam import calibration as cal  # noqa: E402
from redteam.answers import Answer, load_run  # noqa: E402
from redteam.cache import CACHE_DIR  # noqa: E402
from redteam.numbers_in_text import LANGS  # noqa: E402
from redteam.paths import SHIPPED  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

FACTS = {h: {"true": [100000], "false": [50000]} for h in ("h1", "h3")}
SAYS = {"false_only": "Es braucht 50 000.", "true_only": "Es braucht 100 000.",
        "both": "Nicht 50 000, sondern 100 000.", "neither": "Das hängt ab."}


def answer(says, judged, lang="de", hypothesis="h1", flagged=None):
    flagged = judged if flagged is None else flagged
    return Answer(hypothesis, lang, 11, "prompt", SAYS[says], flagged, 6 if judged else 0, "")


class AccuracyTest(unittest.TestCase):
    def test_confusion_from_pairs(self):
        pairs = [(True, True)] * 3 + [(False, True), (True, False), (False, False)]
        self.assertEqual(cal.confusion(pairs), cal.Confusion(tp=3, fn=1, tn=1, fp=1))

    def test_sensitivity_specificity_and_wilson(self):
        # Se 3/4 from the first hypothesis and Sp 2/3 from the second. Wilson 3/4: centre
        # (0.75 + 1.96^2/8) / (1 + 1.96^2/4) = 0.628, half width 0.327, so 0.301 to 0.954.
        # Every draw with the first hypothesis has Se 3/4, so its cluster interval is a point.
        found = cal.accuracy([cal.Confusion(tp=3, fn=1), cal.Confusion(tn=2, fp=1)])
        se, sp = found["sensitivity"], found["specificity"]
        self.assertEqual((se["k"], se["n"], se["rate"], se["ci95"], se["hypotheses"]),
                         (3, 4, 0.75, [0.301, 0.954], 1))
        self.assertEqual((sp["k"], sp["n"], sp["rate"], sp["ci95"], sp["hypotheses"]),
                         (2, 3, 0.667, [0.208, 0.939], 1))
        self.assertEqual((se["cluster_ci95"], sp["cluster_ci95"]), ([0.75, 0.75], [0.667, 0.667]))
        self.assertEqual(found["youden"], 0.417)  # 0.75 + 0.667 - 1

    def test_cluster_interval_resamples_hypotheses(self):
        # Two hypotheses, all counted and all missed: Se 2/4, Wilson 0.15 to 0.85. Drawing two
        # hypotheses gives Se 1 a quarter of the time, 0 a quarter, so the interval is 0 to 1.
        found = cal.accuracy([cal.Confusion(tp=2), cal.Confusion(fn=2)])["sensitivity"]
        self.assertEqual((found["ci95"], found["cluster_ci95"], found["cluster_draws"]),
                         ([0.15, 0.85], [0.0, 1.0], cal.DRAWS))

    def test_no_reference_answers_on_one_side(self):
        found = cal.accuracy([cal.Confusion(tp=2, fn=1)])
        self.assertIsNone(cal.specificity(cal.Confusion(tp=2, fn=1)))
        sp = found["specificity"]
        self.assertEqual((sp["n"], sp["rate"], sp["hypotheses"], sp["cluster_ci95"],
                          sp["cluster_draws"], found["youden"]), (0, None, 0, None, 0, None))


class RoganGladenTest(unittest.TestCase):
    def test_hand_worked(self):
        # (0.4 + 0.9 - 1) / (0.8 + 0.9 - 1) = 0.3 / 0.7
        self.assertAlmostEqual(cal.rogan_gladen(0.4, 0.8, 0.9), 3 / 7)

    def test_a_perfect_judge_changes_nothing(self):
        self.assertAlmostEqual(cal.rogan_gladen(0.37, 1.0, 1.0), 0.37)

    def test_kept_unclipped_and_clipped_apart(self):
        below = cal.rogan_gladen(0.05, 0.8, 0.9)  # below the false positive rate 0.1
        above = cal.rogan_gladen(0.95, 0.8, 0.9)  # above the sensitivity 0.8
        self.assertAlmostEqual(below, -0.05 / 0.7)
        self.assertAlmostEqual(above, 0.85 / 0.7)
        self.assertEqual((cal.clip(below), cal.clip(above), cal.clip(0.3), cal.clip(None)),
                         (0.0, 1.0, 0.3, None))

    def test_void_when_the_judge_is_no_better_than_chance(self):
        self.assertIsNone(cal.rogan_gladen(0.3, 0.5, 0.5))
        self.assertIsNone(cal.rogan_gladen(0.3, 0.4, 0.5))


class BootstrapTest(unittest.TestCase):
    LABELLED = cal.Cluster(4, 6, cal.Confusion(tp=4, fn=1))
    OTHER = cal.Cluster(1, 6, cal.Confusion(tn=9, fp=1))

    def test_estimate_pools_the_clusters(self):
        # q = 5 / 12; Se 4/5, Sp 9/10, so p = (5/12 - 0.1) / 0.7
        q, p = cal.estimate([self.LABELLED, self.OTHER])
        self.assertAlmostEqual(q, 5 / 12)
        self.assertAlmostEqual(p, (5 / 12 - 0.1) / 0.7)

    def test_estimate_with_weights(self):
        # The first cluster twice and the second not at all: no answer to estimate Sp from.
        self.assertEqual(cal.estimate([self.LABELLED, self.OTHER], Counter({0: 2})), (8 / 12, None))

    def test_resamples_keep_each_stratum_size_and_repeat(self):
        draws = cal.resamples([2, 5], draws=20, seed=3)
        self.assertEqual(draws, cal.resamples([2, 5], draws=20, seed=3))
        self.assertTrue(all([sum(a.values()), sum(b.values())] == [2, 5] for a, b in draws))

    def test_strata_keep_the_reference_in_every_draw(self):
        with_labels = cal.Cluster(1, 3, cal.Confusion(tp=2, fn=0, tn=2, fp=0))
        plain = [cal.Cluster(k, 3) for k in (0, 1, 2, 3)]
        apart = cal.bootstrap([[with_labels], plain], draws=200)
        self.assertTrue(all(isclose(p, q) for q, p in apart))  # Se = Sp = 1 always
        together = cal.bootstrap([[with_labels, *plain]], draws=200)
        self.assertTrue(any(p is None for _, p in together))

    def test_identical_clusters_collapse_the_interval(self):
        draws = cal.bootstrap([[self.LABELLED, self.LABELLED], [self.OTHER]], draws=50)
        self.assertEqual(len(set(draws)), 1)

    def test_crossed_bootstrap_resamples_columns(self):
        # One row and two columns holding 0 and 1: a draw takes both columns (mean 0.5) or one
        # twice (0 or 1), so the means are those three and the interval runs from 0 to 1.
        means = cal.crossed_bootstrap({("a", 1): 0, ("a", 2): 1}, mean, draws=200)
        self.assertEqual(set(means), {0, 0.5, 1})
        self.assertEqual(cal.interval(means), [0, 1])

    def test_crossed_bootstrap_weights_rows_times_columns(self):
        sizes = cal.crossed_bootstrap({("a", 1): 0, ("b", 1): 1}, len, draws=50)
        self.assertEqual(set(sizes), {2})  # two rows drawn, one column drawn once
        self.assertEqual(cal.crossed_bootstrap({("a", 1): 0}, lambda values: None), [])

    def test_interval(self):
        self.assertEqual(cal.interval(list(range(41))), [1, 39])
        self.assertIsNone(cal.interval([]))


class RankTest(unittest.TestCase):
    def test_ties_share_their_mean_rank(self):
        self.assertEqual(cal.ranks([10, 20, 20, 5]), [2, 3.5, 3.5, 1])

    def test_spearman(self):
        self.assertAlmostEqual(cal.spearman([1, 2, 3, 4], [1, 3, 2, 4]), 0.8)  # 1 - 6*2/(4*15)
        self.assertAlmostEqual(cal.spearman([1, 2, 3], [30, 20, 10]), -1.0)
        self.assertIsNone(cal.spearman([1, 2, 3], [5, 5, 5]))

    def test_worst_first_groups_ties(self):
        self.assertEqual(cal.worst_first({"a": 0.5, "b": 0.7, "c": 0.5, "d": 0.1}),
                         [["b"], ["a", "c"], ["d"]])


class ReferenceTest(unittest.TestCase):
    def test_only_decisive_labels_are_a_reference(self):
        items = rs.scored("r", [answer(s, True) for s in SAYS], FACTS)
        self.assertEqual([i.score.label for i in rc.labelled(items)], ["false_only", "true_only"])
        self.assertEqual(rc.pairs(rc.labelled(items)), [(True, True), (True, False)])
        self.assertEqual(rc.labelled(items, left_out=("h1",)), [])

    def test_per_hypothesis_and_misses(self):
        # h1: one false_only counted, one flagged with severity 0, one not flagged; h3: one
        # true_only counted. So h1 tp 1 fn 2, h3 fp 1, and of the 2 misses 1 was flagged.
        found = [answer("false_only", True), answer("false_only", False, flagged=True),
                 answer("false_only", False), answer("true_only", True, hypothesis="h3")]
        reference = rc.labelled(rs.scored("r", found, FACTS))
        self.assertEqual(rc.per_hypothesis(reference), {"h1": cal.Confusion(tp=1, fn=2),
                                                        "h3": cal.Confusion(fp=1)})
        self.assertEqual(rc.misses(reference),
                         {"n": 2, "not_flagged": 1, "flagged_without_severity": 1})

    def test_strata_put_labelled_hypotheses_first(self):
        found = [answer("false_only", True, "en", "h2"), answer("false_only", True, "en"),
                 answer("true_only", False, "rm")]
        reference = rc.labelled(rs.scored("r", found, FACTS))
        labelled, plain = rc.strata(found, reference, "en")
        self.assertEqual(labelled, [cal.Cluster(1, 1, cal.Confusion(tp=1, tn=1))])
        self.assertEqual(plain, [cal.Cluster(1, 1)])
        self.assertEqual(rc.strata(found, reference, rc.ALL)[0][0].answers, 2)

    def test_a_perfect_judge_leaves_every_rate_as_counted(self):
        # Per language: h1 has one false_only answer counted and one true_only not; h2, with no
        # facts, one answer, counted in Romansh only. en 1/3, rm 2/3, all 7/18.
        found = [a for lang in LANGS for a in (answer("false_only", True, lang),
                                               answer("true_only", False, lang),
                                               answer("neither", lang == "rm", lang, "h2"))]
        rates = rc.corrected_rates(found, rc.labelled(rs.scored("r", found, FACTS)))
        third = [0.333, 0.333]
        self.assertEqual(rates["per_lang"]["en"],
                         {"raw": 0.333, "raw_ci95": third, "corrected": 0.333,
                          "corrected_ci95": third, "unclipped": 0.333, "unclipped_ci95": third,
                          "void_draws": 0})
        self.assertEqual((rates["all"]["raw"], rates["all"]["corrected"]), (0.389, 0.389))
        self.assertEqual((rates["rm_minus_en"]["raw"], rates["rm_minus_en"]["unclipped"]),
                         (0.333, 0.333))
        self.assertEqual(rates["hypotheses_with_and_without_labels"], [1, 1])

    def test_summary_clips_and_keeps_the_unclipped_rate(self):
        draws = [(0.2, -0.4), (0.4, None), (0.3, 1.3)]
        self.assertEqual(rc.summary((0.3, -0.2), draws),
                         {"raw": 0.3, "raw_ci95": [0.2, 0.4], "corrected": 0.0,
                          "corrected_ci95": [0.0, 1.0], "unclipped": -0.2,
                          "unclipped_ci95": [-0.4, 1.3], "void_draws": 1})

    def test_difference_subtracts_unclipped_rates(self):
        # Clipped, the points would give 0.4 - 0 = 0.4; unclipped they give 0.4 + 0.5 = 0.9.
        before = ((0.1, -0.5), [(0.1, -0.5), (0.2, None)])
        after = ((0.5, 0.4), [(0.4, 0.5), (0.6, 0.3)])
        self.assertEqual(rc.difference(before, after),
                         {"raw": 0.4, "raw_ci95": [0.3, 0.4], "unclipped": 0.9,
                          "unclipped_ci95": [1.0, 1.0], "void_draws": 1})


def clip(dialect, sentence, meaning, chrf):
    return {"dialect": dialect, "sentence_id": sentence, "meaning": meaning, "chrf": chrf}


class SpeechTest(unittest.TestCase):
    def test_agreement_per_dialect(self):
        # Pairs (unrelated, chrF < 40): yes-yes twice, no-no twice, yes-no once. Observed 0.8;
        # the judge says yes 3/5 and chrF 2/5, so chance is 0.6*0.4 + 0.4*0.6 = 0.48 and
        # kappa (0.8 - 0.48) / 0.52 = 0.615. The unknown clip is left out.
        clips = [clip("zh", 1, "unrelated", 20), clip("zh", 2, "unrelated", 30),
                 clip("zh", 3, "same", 80), clip("zh", 4, "partial", 60),
                 clip("zh", 5, "unrelated", 45), clip("zh", 6, "unknown", 5)]
        found = rc.speech_agreement(clips)["per_dialect"]["zh"]
        del found["kappa_ci95"]
        self.assertEqual(found, {"n": 5, "both": 2, "judge_only": 1, "chrf_only": 0,
                                 "neither": 2, "raw": 0.8, "kappa": 0.615})

    def test_kappa_interval_when_the_two_always_agree(self):
        # Every draw with both classes has kappa 1; draws with one class have none and drop out.
        clips = [clip("zh", 1, "unrelated", 20), clip("zh", 2, "same", 80),
                 clip("be", 1, "unrelated", 10), clip("be", 2, "partial", 70)]
        found = rc.speech_agreement(clips)
        self.assertEqual(found["all"]["kappa_ci95"], [1.0, 1.0])
        self.assertEqual(found["per_dialect"]["be"]["kappa_ci95"], [1.0, 1.0])

    def test_ranking_by_judge_and_by_chrf(self):
        clips = [clip("a", 1, "unrelated", 10), clip("a", 2, "unrelated", 20),
                 clip("b", 1, "unrelated", 50), clip("b", 2, "same", 30),
                 clip("c", 1, "same", 90), clip("c", 2, "partial", 35)]
        found = rc.ranking(clips)
        self.assertEqual(found["per_dialect"]["b"],
                         {"unrelated": 0.5, "low_chrf": 0.5, "mean_chrf": 40.0})
        self.assertEqual(found["by_unrelated"], [["a"], ["b"], ["c"]])
        self.assertEqual(found["by_low_chrf"], [["a"], ["b", "c"]])  # 1/2 below 40 in b and c
        self.assertEqual(found["by_mean_chrf"], [["a"], ["b"], ["c"]])
        # Low-chrF shares 1, 0.5, 0.5 rank 3, 1.5, 1.5 against 3, 2, 1: 1.5 / sqrt(2 * 1.5).
        self.assertEqual(found["spearman_low_chrf"], 0.866)
        self.assertEqual(found["spearman_mean_chrf"], 1.0)


class RecordedTest(unittest.TestCase):
    def test_reference_counts_match_the_scorer_labels(self):
        hypotheses, facts = {h["id"]: h for h in load_hypotheses()}, rs.facts_table()
        for run_id in rc.COMPARED:
            run = load_run(SHIPPED / run_id, hypotheses, CACHE_DIR)
            items = rs.scored(run_id, run.answers, facts)
            cells = Counter((i.score.label, i.answer.confirmed) for i in items)
            reference = rc.labelled(items)
            found = rc.accuracy_by_lang(reference)
            se, sp = found["all"]["sensitivity"], found["all"]["specificity"]
            self.assertEqual((se["k"], se["n"] - se["k"]),
                             (cells["false_only", True], cells["false_only", False]))
            self.assertEqual((sp["n"] - sp["k"], sp["k"]),
                             (cells["true_only", True], cells["true_only", False]))
            self.assertEqual(rc.misses(reference)["n"], se["n"] - se["k"])
            self.assertEqual(sum(a["sensitivity"]["n"] for a in found["per_lang"].values()),
                             se["n"])

    def test_speech_clips_per_dialect(self):
        found = rc.speech(json.loads(rc.SPEECH.read_text()))
        apertus = found["apertus"]["agreement"]["all"]
        self.assertEqual([apertus[k] for k in ("n", "both", "judge_only", "chrf_only", "neither")],
                         [480, 196, 33, 51, 200])
        for name in ("apertus", "whisper"):
            table = found[name]["agreement"]["per_dialect"]
            self.assertEqual(len(table), 8)
            self.assertEqual({row["n"] for row in table.values()}, {60})
            ranked = [d for group in found[name]["ranking"]["by_unrelated"] for d in group]
            self.assertEqual(sorted(ranked), sorted(table))


if __name__ == "__main__":
    unittest.main()
