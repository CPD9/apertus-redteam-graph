"""The report scripts run from a plain checkout: the entry point finds src/ itself, and importing
a library script leaves sys.path as it was."""
import subprocess
import sys
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]


def python(*args):
    """Python with PYTHONPATH and the user's site-packages ignored, run outside the checkout."""
    return subprocess.run([sys.executable, "-E", "-s", *args], cwd=TRACK.parent.parent,
                          capture_output=True, text=True, timeout=60)


class EntryPointTest(unittest.TestCase):
    def test_report_figures_runs_without_pythonpath(self):
        done = python(str(TRACK / "scripts" / "report_figures.py"), "--help")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--bank2", done.stdout)

    def test_importing_a_library_script_leaves_sys_path_alone(self):
        code = ("import sys; sys.path[:0] = [sys.argv[1], sys.argv[2]]; before = list(sys.path); "
                "import report_speech; assert sys.path == before, sys.path")
        done = python("-c", code, str(TRACK / "scripts"), str(TRACK / "src"))
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
