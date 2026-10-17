import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.run import load_hypotheses  # noqa: E402


class TitleTest(unittest.TestCase):
    def test_every_hypothesis_has_a_short_unique_title(self):
        hyps = load_hypotheses()
        titles = [h.get("title", "") for h in hyps]
        for h, title in zip(hyps, titles):
            with self.subTest(hypothesis=h["id"]):
                self.assertTrue(title.strip(), "missing title")
                self.assertEqual(title, title.strip())
                self.assertLessEqual(len(title), 40)
        self.assertEqual(len(set(titles)), len(titles), "titles must be unique")

    def test_title_follows_the_id(self):
        for h in load_hypotheses():
            self.assertEqual(list(h)[:2], ["id", "title"], h["id"])


if __name__ == "__main__":
    unittest.main()
