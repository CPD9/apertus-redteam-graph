import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import image_probe as ip  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402
from redteam.stats import wilson  # noqa: E402


def cell(hyp_id, lang, condition, violation=None, error=None):
    c = {"hyp_id": hyp_id, "lang": lang, "condition": condition, "seed": 11}
    if error:
        c["error"] = error
    else:
        c["violation"] = violation
    return c


class ClaimsTest(unittest.TestCase):
    def test_every_claim_has_a_hypothesis_and_both_languages(self):
        ids = {h["id"] for h in load_hypotheses()}
        for hyp_id, claims in ip.FALSE_CLAIMS.items():
            self.assertIn(hyp_id, ids)
            self.assertEqual(set(claims), set(ip.QUESTION))


class PromptTest(unittest.TestCase):
    def test_text_condition_pastes_claim_before_question(self):
        msgs = ip.build_messages("text", "Die Frist ist 6 Monate.", "de", b"")
        self.assertEqual(len(msgs), 1)
        content = msgs[0]["content"]
        self.assertTrue(content.startswith('"Die Frist ist 6 Monate."'))
        self.assertTrue(content.endswith(ip.QUESTION["de"]))

    def test_image_condition_sends_png_and_question_but_not_claim(self):
        png = b"\x89PNG fake bytes"
        content = ip.build_messages("image", "secret claim", "fr", png)[0]["content"]
        image, text = content
        self.assertEqual(image["type"], "image_url")
        prefix, data = image["image_url"]["url"].split(",", 1)
        self.assertEqual(prefix, "data:image/png;base64")
        self.assertEqual(base64.b64decode(data), png)
        self.assertEqual(text, {"type": "text", "text": ip.QUESTION["fr"]})
        self.assertNotIn("secret claim", str(content))


class NoticeTest(unittest.TestCase):
    def test_claim_text_is_escaped(self):
        page = ip.notice_html('<script>x()</script> & "50\'000"', "de")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;x()&lt;/script&gt; &amp; &quot;50&#x27;000&quot;", page)

    def test_heading_and_filler_follow_language(self):
        page = ip.notice_html("x", "fr")
        self.assertIn(ip.HEADING["fr"], page)
        self.assertIn(ip.FILLER["fr"], page)
        self.assertNotIn(ip.HEADING["de"], page)


class SummaryTest(unittest.TestCase):
    CELLS = [cell("a", "de", "image", True), cell("a", "de", "image", False),
             cell("a", "fr", "image", True), cell("b", "de", "text", False),
             cell("b", "fr", "text", error="URLError: timed out")]

    def test_errors_are_counted_but_not_judged(self):
        s = ip.summarise(self.CELLS)
        self.assertEqual(s["errors"], 1)
        self.assertEqual(s["overall"]["text"]["n"], 1)
        self.assertEqual(s["by_lang"]["fr"]["text"]["n"], 0)

    def test_rates_and_wilson_interval(self):
        s = ip.summarise(self.CELLS)
        image = s["overall"]["image"]
        self.assertEqual((image["k"], image["n"]), (2, 3))
        self.assertAlmostEqual(image["rate"], 2 / 3)
        self.assertEqual(image["ci95"], [round(x, 3) for x in wilson(2, 3)])
        self.assertEqual(s["by_hypothesis"]["a"]["text"], {"k": 0, "n": 0, "rate": None,
                                                           "ci95": [0.0, 1.0]})

    def test_table_has_one_row_per_group(self):
        lines = ip.table(ip.summarise(self.CELLS)).splitlines()
        self.assertEqual([ln.split()[0] for ln in lines[1:]], ["ALL", "de", "fr", "a", "b"])
        self.assertIn(" 2/3   67% [", lines[1])
        self.assertTrue(lines[4].rstrip().endswith("-"))


if __name__ == "__main__":
    unittest.main()
