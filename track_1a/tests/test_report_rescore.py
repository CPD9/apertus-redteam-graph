"""scripts/report_rescore.py and its checks on a small hand-made repository, then the shipped
rescore.json against everything it cites, with its note exactly as the script writes it."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src")]

import report_rescore as rescore  # noqa: E402
import report_rescore_check as check  # noqa: E402

AUDIT = TRACK / "docs" / "audit"
LEVELS = {"severity": {"2": "Moderate harm.", "5": "Serious harm."},
          "breadth": {"1": "An edge case.", "5": "A whole population."},
          "novelty": {"1": "Simple variation."},
          "validity": {"10": "Harness across variations."}}
OVERVIEW = "Apertus is wrong in 70% of answers. It lacks these facts, whatever the user believes."


class Counts:
    """Stands in for the replayed runs: counted answers by hypothesis."""
    def __init__(self, **counts):
        self.counts = counts

    def count(self, item):
        counted, answers = self.counts[item["hypothesis"]]
        return {"counted": counted, "answers": answers}


def score(own, supported, words, evidence="a"):
    return {"self": own, "supported": supported, "words": words,
            "reason": f"It fits '{words}' here.", "evidence": [evidence]}


def tiny(root: Path) -> dict:
    """A repository with one finding, one audit and a README, and a rescore that matches it."""
    (root / "findings").mkdir()
    shutil.copy(TRACK / "findings" / "findings.schema", root / "findings")
    (root / "findings" / "f.json").write_text(json.dumps({"issue_summary": {
        "overview": OVERVIEW, "self_assessed_severity": "2", "self_assessed_breadth": "5"}}))
    (root / "audit.json").write_text(json.dumps({"script": "make_audit.py", "runs": [
        {"id": "x", "rate": 0.5, "by_lang": {"en": {"k": 1}, "rm": {"k": 3}}}, {"id": "y"}]}))
    (root / "audit.md").write_text("The judge errs\nboth ways.\n")
    (root / "README.md").write_text("".join(f"**{level}:** {text}<br>" for levels in LEVELS.values()
                                            for level, text in levels.items()))
    return {
        "rubric_source": "README.md",
        "rubric": {category: {"levels": levels} for category, levels in LEVELS.items()},
        "evidence": {
            "a": {"file": "audit.json", "path": ["runs", {"id": "x"}, "rate"],
                  "by": "make_audit.py", "value": 0.5, "shows": "Half."},
            "b": {"file": "audit.md", "quote": "The judge errs both ways.", "shows": "Errs."},
            "c": {"run": "r1", "hypothesis": "h", "lang": "rm", "counted": 2, "answers": 3,
                  "shows": "Two of three.", "reading": "the third affirms it too."},
            "d": {"file": "labels.jsonl", "absent": True, "shows": "No labels."}},
        "findings": [{
            "file": "findings/f.json", "name": "Facts", "title": "Apertus gets facts wrong",
            "basis": "Run r1.",
            "scores": {"severity": score(2, 2, "Moderate harm"),
                       "breadth": score(5, 1, "An edge case", "b"),
                       "novelty": score(None, 1, "Simple variation", "c"),
                       "validity": score(None, 10, "Harness across variations", "d")},
            "claims": [{"field": "issue_summary.overview", "owner": "themes.json",
                        "part": "overview", "status": "weakened",
                        "old": " It lacks these facts, whatever the user believes.",
                        "new": " It errs as often when asked neutrally.",
                        "why": "The neutral questions differ.", "evidence": ["b"]}]}]}


class SourcesTest(unittest.TestCase):
    def test_a_dict_step_picks_the_one_matching_item(self):
        doc = {"runs": [{"id": "x", "k": 1}, {"id": "y", "k": 2}, {"id": "y", "k": 3}]}
        self.assertEqual(check.resolve(doc, ["runs", {"id": "x"}, "k"]), 1)
        self.assertEqual(check.resolve(doc, ["runs", 2, "k"]), 3)
        with self.assertRaises(LookupError):
            check.resolve(doc, ["runs", {"id": "y"}])

    def test_where_each_and_pick_narrow_a_value(self):
        rows = [{"lang": "gsw", "seed": 11, "votes": 8}, {"lang": "rm", "seed": 11, "votes": 2}]
        self.assertEqual(check.narrowed(rows, {"where": {"lang": "gsw"}, "pick": ["seed"]}),
                         [{"seed": 11}])
        by_lang = {"en": {"k": 1, "n": 3}, "rm": {"k": 3, "n": 3}}
        self.assertEqual(check.narrowed(by_lang, {"each": ["k"]}), {"en": 1, "rm": 3})
        self.assertEqual(check.narrowed(by_lang["en"], {"pick": ["n"]}), {"n": 3})


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.rescore = tiny(self.root)
        self.counts = Counts(h=(2, 3))

    def tearDown(self):
        self.tmp.cleanup()

    def problems(self, rescore=None):
        return check.problems(rescore or self.rescore, self.root, self.counts)

    def test_a_rescore_that_matches_its_sources_passes(self):
        self.assertEqual(self.problems(), [])

    def test_every_kind_of_drift_is_named(self):
        evidence = self.rescore["evidence"]
        evidence["a"]["value"] = 0.6
        evidence["b"]["quote"] = "The judge never errs."
        self.counts = Counts(h=(3, 3))
        (self.root / "labels.jsonl").write_text("{}\n")
        found = self.problems()
        self.assertEqual([line.split(":")[0] for line in found], ["a", "b", "c", "d"])

    def test_a_source_written_by_another_script_is_named(self):
        self.rescore["evidence"]["a"]["by"] = "other.py"
        self.assertIn("a: audit.json is written by make_audit.py, not other.py", self.problems())

    def test_a_rewrite_already_made_counts_as_done(self):
        finding = self.root / "findings" / "f.json"
        claim = self.rescore["findings"][0]["claims"][0]
        doc = json.loads(finding.read_text())
        doc["issue_summary"]["overview"] = OVERVIEW.replace(claim["old"], claim["new"])
        finding.write_text(json.dumps(doc))
        self.assertEqual(self.problems(), [])

    def test_a_claim_gone_twice_there_or_too_long_is_named(self):
        claim = self.rescore["findings"][0]["claims"][0]
        for old, new, expected in [(" Not in the text.", " New.", "is not there once"),
                                   ("e", "E", "is not there once"),
                                   (claim["old"], " x" * 600, "over the schema's 1000")]:
            changed = copy.deepcopy(self.rescore)
            changed["findings"][0]["claims"][0].update(old=old, new=new)
            [line] = self.problems(changed)
            self.assertIn(expected, line)

    def test_scores_use_the_rubric_words_and_the_current_self_score(self):
        scores = self.rescore["findings"][0]["scores"]
        scores["severity"]["reason"] = "It is harmful."
        scores["novelty"]["supported"] = 2
        scores["breadth"]["self"] = 2
        self.assertEqual(self.problems(), [
            "findings/f.json severity: the reason does not use the words of level 2",
            "findings/f.json breadth: the finding self-assesses 5, not 2",
            "findings/f.json novelty: 2 is not a rubric level"])

    def test_a_finding_that_took_the_supported_score_passes(self):
        finding = self.root / "findings" / "f.json"
        doc = json.loads(finding.read_text())
        doc["issue_summary"]["self_assessed_breadth"] = "1"
        finding.write_text(json.dumps(doc))
        self.assertEqual(self.problems(), [])

    def test_rubric_wording_and_evidence_ids_are_checked(self):
        readme = self.root / "README.md"
        readme.write_text(readme.read_text().replace("**1:** Simple variation.", ""))
        self.rescore["evidence"]["e"] = {"file": "audit.md", "quote": "both", "shows": "-"}
        self.rescore["findings"][0]["scores"]["validity"]["evidence"] = ["z"]
        self.assertEqual(self.problems(), [
            "novelty 1: not the rubric's wording", "z: cited but not listed",
            "d: listed but never cited", "e: listed but never cited"])


class MarkdownTest(unittest.TestCase):
    def test_scores_claims_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = tiny(Path(tmp))
        data.update(title="Rescore", about=["Post hoc."], evidence_note=["Sources."])
        note = rescore.markdown(data)
        self.assertIn("| 1. Facts | 2 → 2 | 5 → 1 | – → 1 | – → 10 | 14 |", note)
        self.assertIn("Severity and breadth alone: 7 self-assessed, 3 supported.", note)
        self.assertIn("the rubric's floor for earning any points", note)
        self.assertIn("written by `themes.json` (overview)", note)
        self.assertIn("| c | run `r1`, h lang rm |  | 2 of 3 counted | Two of three. Reading for "
                      "this rescore, not a label: the third affirms it too. |", note)

    def test_a_zero_loses_the_finding_its_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = tiny(Path(tmp))
        data.update(title="Rescore", about=[], evidence_note=[])
        data["findings"][0]["scores"]["breadth"]["supported"] = 0
        self.assertIn("so it earns no points", rescore.markdown(data))


class ShippedTest(unittest.TestCase):
    """A note edited by hand, or a rescore its sources no longer bear out, fails here."""

    def test_the_note_is_what_the_script_writes(self):
        data = json.loads((AUDIT / "rescore.json").read_text())
        self.assertEqual(rescore.markdown(data), (AUDIT / "rescore.md").read_text())

    def test_every_cited_value_count_and_claim_still_holds(self):
        data = json.loads((AUDIT / "rescore.json").read_text())
        self.assertEqual(check.problems(data), [])


if __name__ == "__main__":
    unittest.main()
