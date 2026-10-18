import unittest
from fnmatch import fnmatchcase
from pathlib import Path

DOCKERIGNORE = Path(__file__).resolve().parents[1] / ".dockerignore"


def patterns():
    lines = (line.strip() for line in DOCKERIGNORE.read_text().splitlines())
    return [line.rstrip("/") for line in lines if line and not line.startswith("#")]


def matches(pattern, path):
    # Docker matches like Go's filepath.Match: a wildcard never crosses a slash.
    parts, names = pattern.split("/"), path.split("/")
    return len(parts) == len(names) and all(map(fnmatchcase, names, parts))


def ignored(path):
    """Docker leaves a file out of the build when a pattern matches it or a folder above it."""
    names = path.split("/")
    prefixes = ["/".join(names[:i]) for i in range(1, len(names) + 1)]
    return any(matches(pattern, prefix) for pattern in patterns() for prefix in prefixes)


@unittest.skipUnless(DOCKERIGNORE.exists(), "needs a checkout; the image has no .dockerignore")
class DockerContextTest(unittest.TestCase):
    """What `make run` builds into the image: the committed pack, never a live run's loose calls."""

    def test_no_exception_rules(self):
        # ignored() does not model "!" rules; extend it before adding one.
        self.assertFalse([p for p in patterns() if p.startswith("!")])

    def test_loose_cache_files_and_local_runs_stay_out(self):
        for path in ["data/llm_cache/3f/3fa9c2.json", "runs/20261016-172309-1f71/events.jsonl",
                     "web/index.html", ".env"]:
            with self.subTest(path=path):
                self.assertTrue(ignored(path))

    def test_pack_recorded_runs_and_code_go_in(self):
        for path in ["data/llm_cache/pack.jsonl.xz", "data/llm_cache/models.json",
                     "data/runs/20261016-172309-1f71/events.jsonl",
                     "data/runs/speech/20261017-141121/scores.json",
                     "src/redteam/llm.py", "findings/civic_sycophancy.json", "tests/test_llm.py"]:
            with self.subTest(path=path):
                self.assertFalse(ignored(path))


if __name__ == "__main__":
    unittest.main()
