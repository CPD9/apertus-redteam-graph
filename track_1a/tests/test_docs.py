"""Relative links in the READMEs, the report and docs/ point at files that exist, and the commands
the playbooks give name a real module, script or make target."""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.__main__ import COMMANDS  # noqa: E402

TRACK = Path(__file__).resolve().parents[1]
PLAYBOOKS = sorted((TRACK / "docs" / "playbooks").glob("*.md"))
PAGES = [TRACK.parent / "README.md", TRACK / "README.md", TRACK / "technical_report.md",
         *sorted((TRACK / "docs").glob("*.md")), *PLAYBOOKS]
LINK = re.compile(r"\]\(([^)\s]+)\)|src=\"([^\"]+)\"")
CODE = re.compile(r"```bash\n(.*?)```|`([^`\n]+)`", re.S)
MODULE = re.compile(r"python3? -m ([\w.]+)(?: +([a-z][\w-]*))?")
SCRIPT = re.compile(r"python3? (scripts/\w+\.py)")
MAKE = re.compile(r"\bmake ([a-z][\w-]*)")


def local_targets(text):
    """Link and image targets that name a file in the repository (no URL, no bare anchor)."""
    for match in LINK.finditer(text):
        target = (match.group(1) or match.group(2)).split("#")[0]
        if target and not re.match(r"[a-z]+:", target):
            yield target


@unittest.skipUnless((TRACK / "docs").is_dir(), "docs/ is not part of this copy (Docker image)")
class LinkTest(unittest.TestCase):
    def test_every_relative_link_resolves(self):
        for page in PAGES:
            if not page.is_file():
                continue
            for target in local_targets(page.read_text()):
                self.assertTrue((page.parent / target).exists(), f"{page.name} links to {target}")


def make_targets() -> set[str]:
    makefile = (TRACK / "Makefile").read_text()
    shared = re.search(r"^COMMANDS = (.+)$", makefile, re.M).group(1).split()
    return set(re.findall(r"^([a-z][\w-]*):", makefile, re.M)) | set(shared)


def commands(text):
    """Every python -m, python script and make command in the code of a page."""
    for match in CODE.finditer(text):
        code = match.group(1) or match.group(2)
        yield from (("module", m.groups()) for m in MODULE.finditer(code))
        yield from (("script", m.group(1)) for m in SCRIPT.finditer(code))
        yield from (("make", m.group(1)) for m in MAKE.finditer(code))


@unittest.skipUnless(PLAYBOOKS, "docs/playbooks/ is not part of this copy (Docker image)")
class CommandTest(unittest.TestCase):
    def test_every_command_names_something_real(self):
        targets = make_targets()
        for page in [*PLAYBOOKS, TRACK.parent / "README.md", TRACK / "docs" / "HARNESS.md"]:
            if not page.is_file():
                continue
            for kind, what in commands(page.read_text()):
                with self.subTest(page=page.name, command=what):
                    if kind == "module":
                        module, word = what
                        self.assertIsNotNone(importlib.util.find_spec(module))
                        if module == "redteam" and word:
                            self.assertIn(word, COMMANDS)
                    elif kind == "script":
                        self.assertTrue((TRACK / what).is_file())
                    else:
                        self.assertIn(what, targets)

    def test_the_playbooks_give_commands(self):
        for page in PLAYBOOKS:
            self.assertTrue(list(commands(page.read_text())), page.name)


if __name__ == "__main__":
    unittest.main()
