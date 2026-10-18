"""scripts/report_stats.py and its modules on answers small enough to count by hand, and once end
to end on recorded runs as the harness leaves them."""
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from math import erfc, sqrt
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src"), str(TRACK / "tests")]

import helpers  # noqa: E402
import report_stats as stats  # noqa: E402
from report_stats_claims import claims  # noqa: E402
from report_stats_grid import cells, grid, p3, singles, table  # noqa: E402
from report_stats_language import (control_truths, coverage, detectable,  # noqa: E402
                                   different_truths, english_vs, language_effect,
                                   per_hypothesis)
from report_stats_runs import (cell_changes, concordance, mitigation, sizes,  # noqa: E402
                               split_sample)
from redteam import significance as sig  # noqa: E402
from redteam.answers import Answer, Run  # noqa: E402

OTHERS = ["de", "gsw", "fr", "it", "rm"]
DRAWS = 4000


def answers(spec, prompt="p"):
    """Answers from {hypothesis: {lang: "101"}}: one letter per seed, 1 when the answer counts."""
    return [Answer(h, lang, seed, f"{prompt} {h} {lang}", "text", letter == "1",
                   2 * (letter == "1"), "")
            for h, langs in spec.items() for lang, letters in langs.items()
            for seed, letter in enumerate(letters)]


def run(run_id, spec, outcome=None, prompt="p"):
    """A run of spec's answers, every hypothesis a finding unless outcome says otherwise; outcome
    may name hypotheses without answers."""
    langs = list(dict.fromkeys(lang for langs in spec.values() for lang in langs))
    outcome = dict.fromkeys(spec, "finding") | (outcome or {})
    return Run(run_id, "model", "judge", "replay", None, langs, hypotheses=list(outcome),
               seeds=[0, 1, 2], outcome=outcome, answers=answers(spec, prompt))


class GridTest(unittest.TestCase):
    def test_strata(self):
        g = grid(answers({"h": {"en": "110", "rm": "000"}}))
        self.assertEqual(g, {"h": {"en": [1, 1, 0], "rm": [0, 0, 0]}})
        self.assertEqual(cells(g), [[("en", (2, 3)), ("rm", (0, 3))]])
        self.assertEqual(singles(g)[0][:3], [("en", (1, 1)), ("en", (1, 1)), ("en", (0, 1))])
        self.assertEqual(table([1, 1, 0], [0, 0, 0]), (2, 1, 0, 3))

    def test_answers_count_only_when_confirmed(self):
        flagged_at_zero = Answer("h", "en", 0, "p", "t", True, 0, "")
        self.assertEqual(grid([flagged_at_zero]), {"h": {"en": [0]}})

    def test_coverage_names_hypotheses_without_answers(self):
        r = run("r", {"a": {"en": "100"}}, outcome={"b": "no_issue", "c": "error"})
        self.assertEqual(coverage(r), {"hypotheses": 1,
                                       "left_out": {"b": "no_issue", "c": "error"}})


class LanguageTest(unittest.TestCase):
    def test_language_effect(self):
        # Two hypotheses, en none and rm all: variance 1/4. Swapping the two cells of a hypothesis
        # leaves it at 1/4 only when both swap or neither does: p about 1/2, expected 1/8.
        g = grid(answers({h: {"en": "000", "rm": "111"} for h in ("a", "b")}))
        effect = language_effect(g, DRAWS)
        self.assertEqual(effect["rates"], {"en": 0.0, "rm": 1.0})
        self.assertEqual(effect["cells_shuffled"]["observed"], 0.25)
        self.assertAlmostEqual(effect["cells_shuffled"]["p"], 0.5, delta=0.03)
        self.assertAlmostEqual(effect["cells_shuffled"]["expected"], 0.125, delta=0.01)
        self.assertLess(effect["answers_shuffled"]["p"], effect["cells_shuffled"]["p"])

    def test_english_against_german(self):
        # Tables (de counted, de not, en counted, en not): (3,0,0,3) twice and (2,1,1,2). Each has
        # E[a] 1.5 and Var 0.45, so deviation 3.5 and variance 1.35; MH odds ratio
        # (1.5 + 1.5 + 4/6) / (1/6) = 22.
        g = grid(answers({"a": {"en": "000", "de": "111"}, "b": {"en": "000", "de": "111"},
                                "c": {"en": "100", "de": "110"}}))
        row = english_vs(g)["de"]
        self.assertEqual(row["odds_ratio"], 22.0)
        self.assertEqual(row["p"], p3(erfc(sqrt(3.0 ** 2 / 1.35 / 2))))
        self.assertEqual(row["p_holm"], row["p"])
        self.assertEqual(row["sign"], {"higher": 3, "lower": 0, "p": 0.25, "p_holm": 0.25})

    def test_different_truths(self):
        # Hypothesis a splits 3/3 against 0/3; a shuffle splits it when all three 1s land in one
        # cell, 2 of the 20 ways. b has only two 1s, so it can never split.
        g = grid(answers({"a": {"en": "111", "rm": "000"}, "b": {"en": "110", "rm": "000"}}))
        truths = different_truths(g, DRAWS)
        self.assertEqual((truths["hypotheses"], truths["observed"]), (2, 1))
        self.assertAlmostEqual(truths["expected"], 0.1, delta=0.015)
        self.assertAlmostEqual(truths["p"], 0.1, delta=0.015)

    def test_per_hypothesis(self):
        # a and b: English 0 of 3 against 15 of 15, Fisher p 1/816. c: nothing counts, p 1.
        # d: 0 of 3 against 13 of 15: 0 to 3 counted in English weigh 10, 130, 390, 286 of 816,
        # so p 10/816. Holm over four: 4/816 for a and b, 2 * 10/816 for d. Their floors are
        # 1/816, 1/816, 1 and 10/816: three are below 0.05 / 3, so Tarone's family is 3.
        spec = {h: {"en": "000", **dict.fromkeys(OTHERS, "111")} for h in ("a", "b")}
        spec["c"] = {"en": "000", **dict.fromkeys(OTHERS, "000")}
        spec["d"] = {"en": "000", "de": "110", "gsw": "110", "fr": "111", "it": "111", "rm": "111"}
        result = per_hypothesis(grid(answers(spec)))
        self.assertEqual([b["hypothesis"] for b in result["below_alpha"]], ["a", "b", "d"])
        self.assertEqual(result["below_alpha"][0], {
            "hypothesis": "a", "english": "0/3", "others": "15/15", "p": p3(1 / 816),
            "p_holm": p3(4 / 816), "p_tarone": p3(3 / 816)})
        self.assertEqual(result["below_alpha"][2]["p"], p3(10 / 816))
        self.assertEqual(result["below_alpha"][2]["p_holm"], p3(20 / 816))
        self.assertEqual(result["holm_below_alpha"], ["a", "b", "d"])
        self.assertEqual(result["tarone_family"], 3)
        self.assertEqual(result["tarone_below_alpha"], ["a", "b", "d"])
        self.assertEqual(result["floor_p"], p3(1 / 816))
        self.assertEqual(result["floor_p_holm"], p3(4 / 816))
        self.assertEqual(result["cell_floor_p"], p3(1 / 6))

    def test_detectable(self):
        spec = {h: {"en": "100", **dict.fromkeys(OTHERS, "110")} for h in "abcd"}
        result = detectable(grid(answers(spec)), 200)
        self.assertEqual(result["english_rate"], 0.333)
        # Every hypothesis alike: no spread between them, so the ICC is -1 / (18 - 1), every
        # simulated hypothesis sits at the English rate, and both rates needed agree.
        self.assertEqual(result["icc_hypothesis"], p3(-1 / 17))
        self.assertEqual(result["one_hypothesis"]["answers"], [3, 15])
        pooled = result["one_language_pooled"]
        self.assertEqual((pooled["hypotheses"], pooled["answers"]), (4, [3, 3]))
        self.assertEqual(pooled["pooled_rate_needed"], pooled["rate_at_mean_hypothesis"])
        self.assertAlmostEqual(pooled["rate_at_mean_hypothesis"],
                               sig.shifted_rate(1 / 3, pooled["odds_ratio"]), places=2)


class ControlTest(unittest.TestCase):
    def test_neutral_splits_and_logged_rates(self):
        # Premise answers split hypothesis a (en 3/3, rm 0/3), neutral ones split b: each condition
        # has one split the other lacks, McNemar 1/1, p 1. The logged neutral rates of a: en 1/3
        # equals its replayed flags (1 of 3), rm 0.5 does not (0 of 3).
        premise = run("r", {"a": {"en": "111", "rm": "000"}, "b": {"en": "110", "rm": "000"}})
        neutral = answers({"a": {"en": "100", "rm": "000"}, "b": {"en": "111", "rm": "000"}})
        rows = [{"id": "a", "neutral_by_lang": {"en": 1 / 3, "rm": 0.5}}]
        result = control_truths(premise, rows, neutral, 200)
        self.assertEqual(result["logged_rates_equal_raw_flags"], [1, 2])
        self.assertEqual(result["premise_same_hypotheses"]["observed"], 1)
        self.assertEqual(result["neutral"]["observed"], 1)
        self.assertEqual(result["split_in_one_only"], {"premise": 1, "neutral": 1, "p": 1.0})


class PairedRunsTest(unittest.TestCase):
    def test_mitigation_pairs_answers_of_hypotheses_both_runs_finished(self):
        before = run("b", {"a": {"en": "000", "rm": "111"}, "b": {"en": "000", "rm": "110"},
                           "c": {"en": "111", "rm": "111"}})
        after = run("m", {"a": {"en": "110", "rm": "000"}, "b": {"en": "000", "rm": "000"},
                          "c": {"en": "000", "rm": "000"}},
                    outcome={"a": "finding", "b": "not_reproducible", "c": "error"})
        after.answers = [replace(a, prompt="other") if a.hypothesis == "b" else a
                         for a in after.answers]
        result = mitigation(before, after, DRAWS)
        self.assertEqual((result["hypotheses"], result["pairs"]), (2, 12))
        self.assertEqual(result["identical_prompts"], 6)
        self.assertEqual(result["counted_rate"], [p3(5 / 12), p3(2 / 12)])
        # Only without: rm 3 + 2; only with: en 2.
        self.assertEqual(result["mcnemar"], {"only_without": 5, "only_with": 2,
                                             "p": p3(sig.binomial_p(2, 7))})
        english = result["per_lang"]["en"]
        self.assertEqual((english["without"], english["with"]), (0, 2))
        self.assertEqual(english["cmh_by_cell"]["odds_ratio"], 0.0)  # nothing counts without
        self.assertEqual(result["cells"]["higher"], 1)
        self.assertEqual(result["cells"]["lower"], 2)
        self.assertEqual(result["by_hypothesis"], {"higher": 0, "lower": 2, "p": 0.5})
        self.assertEqual(result["selection"]["retested_by_outcome"], {"finding": 3})
        self.assertEqual(result["selection"]["finished_not_retested"], {})
        self.assertEqual(result["selection"]["raw_flag_rate_before"], p3(5 / 12))

    def test_concordance_beside_random_matching(self):
        # One cell, 1 of 3 counted on both sides, matched seed to seed: all 3 pairs agree. Matched
        # at random they agree in (1 * 1 + 2 * 2) / 3 = 5/3 pairs on average.
        pairs = list(zip(answers({"a": {"en": "100"}}), answers({"a": {"en": "100"}})))
        self.assertEqual(concordance(pairs), {"concordant": 3, "concordant_if_unpaired": 1.7})

    def test_split_sample(self):
        # Seeds 0 and 1 of a are flagged, so a is chosen on them; there it counts 2 of 2, on the
        # other seeds' answers 2 of 4 (seeds 1, 2 and then 0, 2). b is never chosen.
        result = split_sample(run("r", {"a": {"en": "110"}, "b": {"en": "000"}}))
        self.assertEqual(result, {"chosen_per_seed": p3(2 / 3), "choosing_seed": 1.0,
                                  "other_seeds": 0.5, "fall": 0.5,
                                  "fall_per_lang": {"en": 0.5}})

    def test_cell_changes_and_the_paired_permutations(self):
        # Both hypotheses rise by 3 answers: flipping the sign of either gives 0, so p about 1/2.
        # Per language en rises by a whole rate in both cells, the same p; rm never changes, p 1.
        first = grid(answers({h: {"en": "000", "rm": "000"} for h in "ab"}))
        second = grid(answers({h: {"en": "111", "rm": "000"} for h in "ab"}))
        changes = cell_changes(first, second, ["en", "rm"], DRAWS)
        self.assertEqual(changes["cells"], {"higher": 2, "lower": 0, "p": 0.5})
        self.assertEqual(changes["cells_per_lang"]["rm"], {"higher": 0, "lower": 0, "p": 1.0,
                                                           "p_holm": 1.0})
        english = changes["cells_per_lang_permutation"]["en"]
        self.assertEqual(english["mean_change"], 1.0)
        self.assertAlmostEqual(english["p"], 0.5, delta=0.03)
        self.assertEqual(changes["cells_per_lang_permutation"]["rm"]["p"], 1.0)
        self.assertEqual(changes["by_hypothesis_permutation"]["observed"], 6)
        self.assertAlmostEqual(changes["by_hypothesis_permutation"]["p"], 0.5, delta=0.03)

    def test_sizes_counts_identical_prompts_and_unbroken_hypotheses(self):
        small = run("s", {"a": {"en": "111", "rm": "111"}, "b": {"en": "000", "rm": "100"},
                          "d": {"en": "111", "rm": "000"}})
        large = run("l", {"a": {"en": "000", "rm": "111"}, "c": {"en": "000", "rm": "000"}},
                    outcome={"d": "no_issue"}, prompt="q")
        result = sizes(small, large, DRAWS)
        self.assertEqual((result["hypotheses"], result["cells_compared"]), (1, 2))
        self.assertEqual(result["identical_prompts"], 0)
        self.assertEqual(result["cells"], {"higher": 0, "lower": 1, "p": 1.0})
        # d counted as none of three on the 70B: its English cell falls too.
        variant = result["unbroken_as_none"]
        self.assertEqual(variant["hypotheses"], 2)
        self.assertEqual(variant["cells"], {"higher": 0, "lower": 2, "p": 0.5})
        self.assertEqual(variant["by_hypothesis"], {"higher": 0, "lower": 2, "p": 0.5})


class ClaimsTest(unittest.TestCase):
    def test_lines_of_each_claim_and_unlisted_intervals(self):
        report = "\n".join(["intro", "difference −14 points, 95% CI −23 to −5), but",
                            "a 95% CI here", "![**Figure 2.** caption"])
        found = claims(report)
        self.assertEqual(found["claims"][0]["lines"], [2])
        figure = next(c for c in found["claims"] if c["reading"]["assumes_independence"])
        self.assertEqual(figure["lines"], [4])
        self.assertEqual(found["unlisted_lines"], [3])


class MainTest(unittest.TestCase):
    """End to end on recorded runs: the 70B and the mitigated run replay the same answers, so
    nothing changes between them."""

    def test_writes_numbers_and_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs, cache = root / "runs", root / "cache"
            for run_id in ("r8", "r70", "rm"):
                helpers.write_run(runs, cache, run_id)
            helpers.write_control(runs, cache, "r8")
            helpers.use_runs(self, runs)
            (root / "report.md").write_text("a 95% CI here\n")
            numbers = stats.main(out=root / "audit", report=root / "report.md", cache_root=cache,
                                 ids=("r8", "r70", "rm"), draws=200, power_draws=200)
            self.assertEqual(json.loads((root / "audit" / "stats.json").read_text()), numbers)
            note = (root / "audit" / "stats.md").read_text()
        self.assertEqual(numbers["mitigation"]["pairs"], 45)
        self.assertEqual(numbers["mitigation"]["identical_prompts"], 45)
        self.assertEqual(numbers["mitigation"]["mcnemar"]["p"], 1.0)
        self.assertEqual(numbers["sizes"]["cells_compared"], 15)
        self.assertIn("control_truths", numbers["runs"]["r8"])
        self.assertNotIn("control_truths", numbers["runs"]["r70"])
        self.assertEqual(numbers["report_claims"]["unlisted_lines"], [1])
        for heading in range(1, 9):
            self.assertIn(f"## {heading}. ", note)


if __name__ == "__main__":
    unittest.main()
