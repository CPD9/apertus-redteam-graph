"""Relative links in the READMEs, the report and docs/ point at files that exist."""
import re
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
PAGES = [TRACK.parent / "README.md", TRACK / "README.md", TRACK / "technical_report.md",
         *sorted((TRACK / "docs").glob("*.md"))]
LINK = re.compile(r"\]\(([^)\s]+)\)|src=\"([^\"]+)\"")


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


if __name__ == "__main__":
    unittest.main()
