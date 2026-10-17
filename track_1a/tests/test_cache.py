import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src")]

import pack_cache  # noqa: E402
from redteam import paths  # noqa: E402
from redteam.cache import CACHE_DIR, PACK, Cached, CacheMiss  # noqa: E402
from redteam.graph import Config, run  # noqa: E402
from redteam.llm import MODELS_FILE, MockLLM, Router  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402
from redteam.stats import wilson  # noqa: E402

MSG = [{"role": "user", "content": "TEXT: hello"}]


class CacheTest(unittest.TestCase):
    def test_replay_returns_recorded_answer_without_client(self):
        with tempfile.TemporaryDirectory() as d:
            live = Cached(MockLLM(), "m", root=Path(d))
            first = live.chat(MSG, role="target", seed=1)
            replay = Cached(None, "m", replay=True, root=Path(d))
            self.assertEqual(replay.chat(MSG, role="target", seed=1), first)

    def test_replay_miss_is_loud(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(CacheMiss):
                Cached(None, "m", replay=True, root=Path(d)).chat(MSG, role="target", seed=2)


class Numbered:
    """A client whose every answer names the seed it was asked with."""
    backend = "stub"

    def chat(self, messages, *, role, seed=None, **kw):
        return f"answer {seed}"


def record(root: Path, seeds) -> dict[int, str]:
    """Live calls through the cache, as a run makes them: each stored as its own file."""
    live = Cached(Numbered(), "m", root=root)
    return {seed: live.chat(MSG, role="target", seed=seed) for seed in seeds}


def replayed(root: Path, seeds) -> dict[int, str]:
    replay = Cached(None, "m", replay=True, root=root)
    return {seed: replay.chat(MSG, role="target", seed=seed) for seed in seeds}


def pack(root: Path, prune: bool = True) -> bytes:
    with contextlib.redirect_stdout(io.StringIO()):
        pack_cache.main(["--root", str(root)] + (["--prune"] if prune else []))
    return (root / PACK).read_bytes()


class PackTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.recorded = record(self.root, [1, 2, 3])

    def test_replay_answers_from_the_pack_alone(self):
        pack(self.root)
        self.assertEqual(list(self.root.iterdir()), [self.root / PACK])
        self.assertEqual(replayed(self.root, [1, 2, 3]), self.recorded)
        with self.assertRaises(CacheMiss):
            replayed(self.root, [4])

    def test_own_file_wins_over_the_pack(self):
        own = {json.loads(f.read_text())["content"]: f for f in self.root.glob("??/*.json")}
        pack(self.root)
        own["answer 2"].parent.mkdir(exist_ok=True)
        own["answer 2"].write_text(json.dumps({"role": "target", "model": "m", "content": "new"}))
        self.assertEqual(replayed(self.root, [1, 2, 3]), {**self.recorded, 2: "new"})

    def test_repacking_keeps_every_entry_and_the_same_entries_give_the_same_bytes(self):
        pack(self.root)
        self.assertEqual(record(self.root, [1]), {1: "answer 1"})  # answered from the pack
        self.assertEqual(pack_cache.own_files(self.root), {})
        newer = record(self.root, [4])
        second = pack(self.root)
        self.assertEqual(replayed(self.root, [1, 2, 3, 4]), {**self.recorded, **newer})
        self.assertEqual(pack(self.root), second)

    def test_nothing_is_deleted_without_prune(self):
        pack(self.root, prune=False)
        self.assertEqual(len(pack_cache.own_files(self.root)), 3)
        self.assertEqual(replayed(self.root, [1, 2, 3]), self.recorded)

    def test_a_pack_that_does_not_read_back_equal_changes_nothing(self):
        first = pack(self.root, prune=False)
        record(self.root, [4])
        old = pack_cache.read_pack(self.root / PACK)
        with mock.patch.object(pack_cache, "read_pack", side_effect=[old, {}]):
            with self.assertRaises(SystemExit):
                pack(self.root, prune=True)
        self.assertEqual((self.root / PACK).read_bytes(), first)
        self.assertEqual(len(pack_cache.own_files(self.root)), 4)
        self.assertFalse((self.root / (PACK + ".new")).exists())


class ShippedPackTest(unittest.TestCase):
    def test_canonical_run_replays_from_the_shipped_pack_alone(self):
        recorded = json.loads(MODELS_FILE.read_text())
        summary = json.loads((paths.SHIPPED / recorded["run_id"] / "summary.json").read_text())
        hypotheses = [h for h in load_hypotheses() if h["id"] in recorded["hypotheses"]]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "cache"
            root.mkdir()
            (root / PACK).symlink_to(CACHE_DIR / PACK)
            llm = Router(Cached(None, recorded["target"], replay=True, root=root),
                         Cached(None, recorded["red"], replay=True, root=root))
            replay = run(llm, hypotheses, Config(out_dir=Path(d) / "runs"))
        status = {r["id"]: (r["status"], r.get("overall")) for r in replay["results"]}
        self.assertEqual(status, {r["id"]: (r["status"], r.get("overall"))
                                  for r in summary["results"]})


class WilsonTest(unittest.TestCase):
    def test_bounds(self):
        lo, hi = wilson(0, 3)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.5)  # 0/3 is not evidence of "never"
        lo, hi = wilson(18, 18)
        self.assertGreater(lo, 0.8)


if __name__ == "__main__":
    unittest.main()
