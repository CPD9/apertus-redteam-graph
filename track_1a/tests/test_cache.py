import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.cache import Cached, CacheMiss  # noqa: E402
from redteam.llm import MockLLM  # noqa: E402
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


class WilsonTest(unittest.TestCase):
    def test_bounds(self):
        lo, hi = wilson(0, 3)
        self.assertEqual(lo, 0.0)
        self.assertGreater(hi, 0.5)  # 0/3 is not evidence of "never"
        lo, hi = wilson(18, 18)
        self.assertGreater(lo, 0.8)


if __name__ == "__main__":
    unittest.main()
