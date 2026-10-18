"""python -m redteam hands each command to the module or script that does the work."""
import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import __main__ as cli  # noqa: E402

TRACK = Path(__file__).resolve().parents[1]


def redteam(*args):
    env = {**os.environ, "PYTHONPATH": str(TRACK / "src")}
    return subprocess.run([sys.executable, "-m", "redteam", *args], capture_output=True,
                          text=True, cwd=TRACK, env=env, timeout=60)


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.steps = []
        patches = [mock.patch.object(cli, "step", side_effect=self.record),
                   mock.patch.object(cli.os, "chdir"), mock.patch("sys.stdout")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def record(self, target, args):
        self.steps.append((target, *args))
        return 0

    def test_arguments_follow_the_fixed_ones(self):
        self.assertEqual(cli.main(["replay", "--only", "x"]), 0)
        self.assertEqual(cli.main(["figures", "--out", "f"]), 0)
        figures = ("scripts/report_figures.py", *cli.REPORT_RUNS, "--out", "f")
        self.assertEqual(self.steps, [("redteam.run", "--replay", "--only", "x"), figures])

    def test_audit_runs_every_script_in_order(self):
        self.assertEqual(cli.main(["audit"]), 0)
        self.assertEqual(self.steps, cli.AUDIT)

    def test_a_failing_step_stops_the_rest(self):
        cli.step.side_effect = lambda target, args: self.record(target, args) or 3
        self.assertEqual(cli.main(["audit"]), 3)
        self.assertEqual(len(self.steps), 1)

    def test_a_command_without_arguments_answers_help_itself(self):
        for name in ("check", "audit", "dashboard", "labels"):
            with self.subTest(name=name), mock.patch("sys.stderr") as stderr:
                self.assertEqual(cli.main([name, "--help"]), 0)
                stderr.write.assert_not_called()
                self.assertEqual(cli.main([name, "--port", "1"]), 2)
                stderr.write.assert_called()
        self.assertEqual(self.steps, [])

    def test_unknown_command(self):
        with mock.patch("sys.stderr") as stderr:
            self.assertEqual(cli.main(["nope"]), 2)
        self.assertIn("unknown command: nope", "".join(c.args[0] for c in stderr.write.mock_calls))


class CommandTest(unittest.TestCase):
    def test_every_step_names_a_module_or_script(self):
        for name, command in cli.COMMANDS.items():
            for target, *_ in command.steps:
                with self.subTest(command=name, target=target):
                    if target.endswith(".py"):
                        self.assertTrue((TRACK / target).is_file())
                    else:
                        self.assertIsNotNone(importlib.util.find_spec(target))

    @unittest.skipUnless((TRACK / "Makefile").is_file(), "the Docker image has no Makefile")
    def test_make_targets_are_commands(self):
        line = re.search(r"^COMMANDS = (.+)$", (TRACK / "Makefile").read_text(), re.M)
        self.assertLessEqual(set(line.group(1).split()), set(cli.COMMANDS))

    def test_no_command_prints_the_map(self):
        out = redteam()
        self.assertEqual(out.returncode, 0)
        for name in cli.COMMANDS:
            self.assertRegex(out.stdout, rf"\n  {name} ")

    def test_help_and_exit_status_come_from_the_module(self):
        for name, usage in [("run", "usage: run.py"), ("reproduce", "usage: reproduce.py"),
                            ("report", "usage: build_report.py")]:
            with self.subTest(name=name):
                out = redteam(name, "--help")
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertTrue(out.stdout.startswith(usage), out.stdout)
        self.assertEqual(redteam("reproduce", "--no-such-flag").returncode, 2)


if __name__ == "__main__":
    unittest.main()
