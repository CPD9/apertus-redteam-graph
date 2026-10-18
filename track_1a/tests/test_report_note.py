"""The notes in docs/audit: rounding and wording helpers on hand-picked values, and each shipped
note being exactly what its script writes from the JSON beside it."""
import json
import sys
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src")]

import report_calibration_note as calibration_note  # noqa: E402
import report_scorer as rs  # noqa: E402
import report_scorer_note as scorer_note  # noqa: E402
import report_stats_note as stats_note  # noqa: E402
from report_note import holds, listed, percent, rounded, signed, spread  # noqa: E402

AUDIT = TRACK / "docs" / "audit"


class RoundingTest(unittest.TestCase):
    def test_half_up_with_a_true_minus(self):
        self.assertEqual(rounded(0.6747), "0.67")
        self.assertEqual(rounded(0.125), "0.13")
        self.assertEqual(rounded(-0.009), "−0.01")
        self.assertEqual(rounded(-0.001), "0.00")
        self.assertEqual(rounded(1.0), "1.00")

    def test_a_five_rounded_once_already_is_kept(self):
        # 0.675 in a JSON of three decimals may be 0.6747: shown as it is, not as 0.68.
        self.assertEqual(rounded(0.675, stored=3), "0.675")
        self.assertEqual(rounded(0.676, stored=3), "0.68")
        self.assertEqual(rounded(0.125, stored=4), "0.13")  # four decimals: 0.1250, exact
        self.assertEqual(percent(0.825, stored=3), "82.5")
        self.assertEqual(percent(0.125, stored=4), "13")

    def test_signed(self):
        self.assertEqual(signed(percent(0.375)), "+38")
        self.assertEqual(signed(percent(-0.0476)), "−5")
        self.assertEqual(signed(rounded(0)), "0.00")


class WordingTest(unittest.TestCase):
    def test_lists_and_ranges(self):
        self.assertEqual(listed([3]), "3")
        self.assertEqual(listed([3, 9]), "3 and 9")
        self.assertEqual(listed([0, 5, 9]), "0, 5 and 9")
        self.assertEqual(spread([8, 7, 8], "or"), "7 or 8")
        self.assertEqual(spread([8, 8], "to"), "8")

    def test_a_sentence_the_numbers_no_longer_bear_out_stops_the_note(self):
        holds(True, "fine")
        with self.assertRaises(SystemExit) as stopped:
            holds(False, "no scorer gap passes a sign test")
        self.assertIn("no scorer gap passes a sign test", str(stopped.exception))


class ShippedNotesTest(unittest.TestCase):
    """A note edited by hand, or a JSON written without its note, fails here."""

    def read(self, name):
        return json.loads((AUDIT / f"{name}.json").read_text())

    def test_scorer(self):
        self.assertEqual(scorer_note.markdown(self.read("scorer"), rs.WIDTH),
                         (AUDIT / "scorer.md").read_text())

    def test_calibration(self):
        self.assertEqual(calibration_note.markdown(self.read("calibration"), rs.load_reading()),
                         (AUDIT / "calibration.md").read_text())

    def test_stats(self):
        self.assertEqual(stats_note.markdown(self.read("stats")), (AUDIT / "stats.md").read_text())


if __name__ == "__main__":
    unittest.main()
