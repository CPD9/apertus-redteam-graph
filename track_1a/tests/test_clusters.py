import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import REFS  # noqa: E402
from redteam import clusters, group, theme_finding, theme_notes  # noqa: E402
from redteam.answers import Answer, Run, of, share  # noqa: E402
from redteam.stats import cluster_bootstrap  # noqa: E402

LANGS = ["en", "de", "fr", "it"]
THEME = {**group.THEMES[0], "id": "t", "families": {"vote_": "voting rules"}}
RUN = Run("r", "swiss-ai/Apertus-v1.5-8B", "apertus-70b-fp8", "vllm", None, LANGS,
          seeds=[0, 1, 2])


def answers(counted: dict[str, int]) -> list[Answer]:
    """Three answers per variation and language, the first `counted` of them asserting the error,
    the same in every language."""
    out = []
    for hyp, k in counted.items():
        for lang in LANGS:
            out += [Answer(hyp, lang, seed, "q", "a", seed < k, 8 if seed < k else 0, "")
                    for seed in range(3)]
    return out


def measured(counted: dict[str, int], neutral: dict[str, int] | None = None) -> group.Measured:
    pooled = answers(counted)
    m = group.Measured(THEME, list(counted), pooled, [], None, None)
    if neutral:
        m.neutral = answers(neutral)
        m.control = (share(pooled), share(m.neutral))
    return m


class PooledIntervalTest(unittest.TestCase):
    def test_two_variations_at_100_and_0_percent_are_wider_than_wilson(self):
        # 12 of 24 answers count, but all of them answer one of the two prompts.
        m = measured({"vote_a": 3, "vote_b": 0})
        stored = theme_finding.parameters(m, RUN, "r")["harness_overall_ci95"]
        wilson_low, wilson_high = share(m.answers).ci95
        self.assertEqual(stored, [0.0, 1.0])
        self.assertLess(stored[0], wilson_low)
        self.assertGreater(stored[1], wilson_high)

    def test_the_overview_states_the_stored_interval(self):
        m = measured({"vote_a": 3, "vote_b": 0})
        self.assertIn("12 of 24 verified answers (50%, 95% CI 0%-100%)",
                      theme_finding.overview(m, RUN))

    def test_cells_that_cannot_vary_keep_the_wilson_interval(self):
        pooled = answers({"vote_a": 3})
        wilson = [round(x, 3) for x in share(pooled).ci95]
        self.assertEqual(clusters.interval(pooled, LANGS), wilson)

    def test_each_variation_keeps_its_wilson_interval(self):
        m = measured({"vote_a": 3, "vote_b": 0})
        p = theme_finding.parameters(m, RUN, "r")
        self.assertEqual(p["harness_variations"][0]["ci95"], m.share_of("vote_a").brief()["ci95"])
        self.assertEqual(p["harness_ci95_method"]["per_variation"], "Wilson")
        self.assertEqual(p["harness_ci95_method"]["draws"], 2000)

    def test_the_notes_say_how_little_one_variation_resamples(self):
        notes = theme_notes.notes(measured({"vote_mandatory_referendum": 3}), RUN, "r", REFS)
        self.assertIn("With one variation, they resample only the 4 languages", notes)
        self.assertNotIn("With one variation", clusters.explained(3, 4))

    def test_the_notes_say_the_interval_is_never_narrower_than_wilson(self):
        # A neutral control at 0 of 3 in every cell gives the same share in every draw, so the
        # interval printed for it is Wilson's.
        for variations in (1, 2, 3):
            self.assertIn("never narrower than Wilson's", clusters.explained(variations, 6))

    def test_the_group_table_gives_the_theme_its_clustered_interval(self):
        m = measured({"vote_a": 3, "vote_b": 0})
        theme, first, second = group.table([m], RUN, []).splitlines()[1:]
        self.assertIn(" 50%   0%-100%", theme)
        self.assertNotIn("31%-69%", theme)  # Wilson's for 12 of 24
        self.assertIn("100%  76%-100%", first)
        self.assertIn("  0%    0%-24%", second)


class DifferenceTest(unittest.TestCase):
    def test_only_cells_asked_both_ways_are_paired(self):
        premise = answers({"vote_a": 3, "vote_b": 3})
        neutral = answers({"vote_a": 0})  # vote_b was never asked neutrally
        # Newcombe's interval for 12 of 12 against 0 of 12; with vote_b's 12 answers it would be
        # narrower.
        self.assertEqual(clusters.difference(premise, neutral, LANGS), [0.657, 1.0])
        self.assertEqual(clusters.rounded(clusters.newcombe(of(premise, {"vote_a"}), neutral)),
                         [0.657, 1.0])

    def test_the_same_difference_in_every_cell_still_leaves_an_interval(self):
        # Every language: 1 of 3 with the premise, 0 of 3 without. The draws all give 33 points.
        premise, neutral = answers({"vote_a": 1}), answers({"vote_a": 0})
        same = {("vote_a", lang): 1 / 3 for lang in LANGS}
        self.assertEqual(clusters.rounded(cluster_bootstrap(same)), [0.333, 0.333])
        self.assertEqual(clusters.difference(premise, neutral, LANGS), [0.022, 0.609])
        self.assertIn("(premise minus neutral: +2 to +61 points, 95% CI paired by variation",
                      theme_finding.contrast(measured({"vote_a": 1}, neutral={"vote_a": 0}),
                                             LANGS))

    def test_newcombe_matches_the_published_example(self):
        # Newcombe (1998), Statistics in Medicine 17:873, example (a): 56/70 - 48/80.
        premise = [Answer("h", "en", i, "q", "a", i < 56, 8, "") for i in range(70)]
        neutral = [Answer("h", "en", i, "q", "a", i < 48, 8, "") for i in range(80)]
        low, high = clusters.newcombe(premise, neutral)
        self.assertAlmostEqual(low, 0.0524, places=4)
        self.assertAlmostEqual(high, 0.3339, places=4)

    def test_two_prompts_cannot_show_that_the_premise_matters(self):
        # Wilson would separate 12 of 24 from 0 of 24, but one of the two prompts makes no
        # difference at all.
        m = measured({"vote_a": 3, "vote_b": 0}, neutral={"vote_a": 0, "vote_b": 0})
        self.assertEqual(clusters.difference(m.answers, m.neutral, LANGS), [0.0, 1.0])
        self.assertIn("a difference within chance over these variations and languages (premise "
                      "minus neutral: +0 to +100 points", theme_finding.contrast(m, LANGS))

    def test_a_neutral_error_reads_as_missing_knowledge(self):
        m = measured({"vote_a": 0}, neutral={"vote_a": 3})
        self.assertIn("so Apertus lacks these facts even when nobody suggests a wrong one (premise "
                      "minus neutral: -100 to -66 points", theme_finding.contrast(m, LANGS))

    def test_the_control_stores_clustered_intervals_on_both_sides(self):
        m = measured({"vote_a": 3, "vote_b": 3}, neutral={"vote_a": 0, "vote_b": 1})
        p = theme_finding.parameters(m, RUN, "r")
        control = p["harness_control"]
        self.assertEqual(control["neutral"]["ci95"], clusters.interval(m.neutral, LANGS))
        # The bootstrap alone gives [0.667, 1.0]; Newcombe's interval for 24 of 24 against 4 of 24
        # is wider.
        self.assertEqual(control["premise_minus_neutral_ci95"], [0.597, 1.0])
        self.assertIn("Newcombe", p["harness_ci95_method"]["premise_minus_neutral"])
        self.assertIn("clearly more likely (premise minus neutral: +60 to +100 points, 95% CI "
                      "paired by variation and language, never narrower than Newcombe's).",
                      theme_finding.contrast(m, LANGS))


if __name__ == "__main__":
    unittest.main()
