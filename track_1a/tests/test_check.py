import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import use_runs  # noqa: E402
from redteam import check, group, scribe  # noqa: E402

SUBMITTED = check.FINDINGS
FIVE = {*(f"{theme['id']}.json" for theme in group.THEMES), "speech_dialect_hallucination.json"}
COMMIT = re.compile(r"[0-9a-f]{40}")


class CheckTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.findings = Path(d.name) / "findings"
        self.findings.mkdir()
        use_runs(self, Path(d.name) / "runs")
        patcher = mock.patch.object(check, "FINDINGS", self.findings)
        patcher.start()
        self.addCleanup(patcher.stop)

    def main(self) -> tuple[int, str]:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = check.main()
        return code, out.getvalue()

    def test_valid_findings_pass(self):
        shutil.copy(SUBMITTED / "civic_sycophancy.json", self.findings)
        self.assertEqual(self.main(), (0, f"OK   {self.findings / 'civic_sycophancy.json'}\n"
                                          "1/1 findings files valid\n"))

    def test_more_than_five_submitted_findings_fail(self):
        for i in range(6):
            shutil.copy(SUBMITTED / "civic_sycophancy.json", self.findings / f"f{i}.json")
        code, out = self.main()
        self.assertEqual(code, 1)
        self.assertIn("6/6 findings files valid", out)
        self.assertIn("FAIL 6 findings files in findings/, at most 5 allowed", out)

    def test_an_invalid_finding_fails(self):
        (self.findings / "bad.json").write_text(json.dumps({"issue_title": 3}))
        code, out = self.main()
        self.assertEqual(code, 1)
        self.assertIn("$.issue_title: expected string", out)


class SubmissionTest(unittest.TestCase):
    """The findings/ folder as submitted: five files, each named by its theme, licensed."""

    def test_exactly_the_five_findings_are_submitted(self):
        self.assertEqual({p.name for p in SUBMITTED.glob("*.json")}, FIVE)

    def test_each_finding_has_a_sentence_title_and_a_model_version(self):
        for name in FIVE:
            finding = json.loads((SUBMITTED / name).read_text())
            self.assertEqual(scribe.validate(finding), [], name)
            title = finding["issue_summary"]["title"]
            self.assertNotEqual(title, name.removesuffix(".json"))
            self.assertIn(" ", title)
            self.assertRegex(finding["model"]["version"], COMMIT)

    def test_findings_carry_the_data_licence(self):
        licence = (SUBMITTED / "LICENSE").read_text()
        self.assertTrue(licence.startswith("Community Data License Agreement - Permissive - "
                                           "Version 2.0"))


if __name__ == "__main__":
    unittest.main()
