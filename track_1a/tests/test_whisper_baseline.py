"""The weight commits the pod scripts load match the ones the report cites (models.REVISIONS)."""
import re
import sys
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
RUNPOD = TRACK / "infra" / "runpod"
sys.path[:0] = [str(RUNPOD), str(TRACK / "src")]

from redteam.models import REVISIONS  # noqa: E402


@unittest.skipUnless(RUNPOD.is_dir(), "infra/ is not part of this copy (Docker image)")
class RevisionTest(unittest.TestCase):
    def setUp(self):
        import whisper_baseline
        self.wb = whisper_baseline

    def args(self, *extra):
        return self.wb.parse_args(["clips", "out.json", *extra])

    def test_the_default_model_loads_the_commit_the_findings_name(self):
        self.assertEqual(self.args().revision, REVISIONS[self.wb.DEFAULT_MODEL])

    def test_another_model_loads_its_main_branch(self):
        self.assertIsNone(self.args("--model", "openai/whisper-large-v3").revision)

    def test_an_explicit_revision_wins(self):
        for model in [self.wb.DEFAULT_MODEL, "openai/whisper-large-v3"]:
            with self.subTest(model=model):
                self.assertEqual(self.args("--model", model, "--revision", "abc123").revision,
                                 "abc123")


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(RUNPOD.is_dir(), "infra/ is not part of this copy (Docker image)")
class ServeScriptTest(unittest.TestCase):
    def test_each_serve_script_pins_the_commit_the_report_cites(self):
        for script in sorted(RUNPOD.glob("serve_*.sh")):
            text = script.read_text()
            model = re.search(r"vllm serve (\S+)", text)
            if not model or model.group(1) not in REVISIONS:
                continue
            with self.subTest(script=script.name):
                self.assertIn(f"REVISION={REVISIONS[model.group(1)]}\n", text)
                self.assertIn('--revision "$REVISION" --tokenizer-revision "$REVISION"', text)
