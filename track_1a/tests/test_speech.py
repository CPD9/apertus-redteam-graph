import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.speech_eval import chrf  # noqa: E402


class ChrfTest(unittest.TestCase):
    def test_identical_strings_score_100(self):
        text = "Derzeit ist er in Parasite zu sehen."
        self.assertAlmostEqual(chrf(text, text), 100.0)

    def test_unrelated_strings_score_low(self):
        self.assertLess(chrf("Der Hund bellt laut im Garten.", "Quarzuhr mit Kompass, 1987 gekauft."), 20)


if __name__ == "__main__":
    unittest.main()
