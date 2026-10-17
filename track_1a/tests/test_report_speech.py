"""The speech figure: Apertus next to Whisper per dialect, from a speech run or its shipped
scores."""
import sys
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src"), str(TRACK / "tests")]

import report_runs as runs  # noqa: E402
import report_speech as speech  # noqa: E402
from report_helpers import Isolated, texts, write_scores, write_speech  # noqa: E402
from redteam.stats import cluster_bootstrap  # noqa: E402


class SpeechTest(Isolated):
    def test_whisper_next_to_apertus_with_a_cluster_interval(self):
        folder = write_speech(self.root / "speech", {"zh": "uups", "vs": "uuuu"},
                              {"zh": "spss", "vs": "ssss"})
        svg, numbers = speech.speech_dialects(folder)
        self.assertEqual([(r["dialect"], r["apertus"]["k"], r["whisper"]["k"])
                          for r in numbers["rows"]], [("vs", 4, 0), ("zh", 2, 0)])
        pooled = numbers["all"]["apertus"]
        self.assertEqual((pooled["k"], pooled["n"]), (6, 8))
        values = {(d, i): float(v == "u") for d, letters in (("zh", "uups"), ("vs", "uuuu"))
                  for i, v in enumerate(letters)}
        self.assertEqual(pooled["ci95"], [round(x, 3) for x in cluster_bootstrap(values)])
        # Two speakers, so the interval over all clips is wider than one for 8 independent clips.
        self.assertGreater(pooled["ci95"][1], pooled["wilson_ci95"][1])
        labels = " ".join(texts(svg))
        for expected in ("Valais (VS)", "All dialects", "Swiss German Whisper",
                         "cluster bootstrap over dialects and sentences",
                         "the model that translated"):
            self.assertIn(expected, labels)

    def test_shipped_scores_draw_the_same_figure(self):
        grids = ({"zh": "uups", "vs": "uuuu"}, {"zh": "spss", "vs": "ssss"})
        svg, numbers = speech.speech_dialects(write_speech(self.root / "run", *grids))
        shipped, shipped_numbers = speech.speech_dialects(write_scores(self.root / "data", *grids))
        self.assertEqual(texts(shipped), texts(svg))
        self.assertEqual({**shipped_numbers, "folder": None}, {**numbers, "folder": None})

    def test_sentences_unrelated_in_every_dialect_are_listed(self):
        # Sentence 0 is unrelated everywhere; 1 and 2 are judged same or partial in one dialect;
        # Bern has no clip of sentence 3.
        folder = write_speech(self.root / "speech", {"zh": "uupu", "vs": "uuuu", "be": "usu"},
                              {"zh": "ssss", "vs": "ssss", "be": "sss"})
        _, numbers = speech.speech_dialects(folder)
        self.assertEqual(numbers["unrelated_in_every_dialect"], [0])

    def test_a_run_without_the_whisper_comparison_is_skipped(self):
        folder = write_speech(self.root / "speech", {"vs": "uu"}, {"vs": "ss"})
        (folder / "whisper_compare.json").unlink()
        with self.assertRaises(runs.Skip):
            speech.speech_dialects(folder)


if __name__ == "__main__":
    unittest.main()
