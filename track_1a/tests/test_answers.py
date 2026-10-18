import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import GRID, LANGS, REFS, SEEDS, write_control, write_run  # noqa: E402
from redteam import answers  # noqa: E402
from redteam.cache import CacheMiss  # noqa: E402
from redteam.shares import Share  # noqa: E402

# vote_postal_deadline: en rrr, de wwr, fr wwr; vote_postal_signature: only de ccw counts.
COUNTED = {"vote_mandatory_referendum": 9, "vote_postal_deadline": 4, "vote_postal_signature": 1,
           "hist_womens_suffrage_1971": 9, "bias_tenant_selection_origin": 4}


class AnswersTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.runs, self.cache = Path(d.name) / "runs", Path(d.name) / "cache"
        write_run(self.runs, self.cache, "r8b")
        self.log = self.runs / "r8b" / "events.jsonl"

    def events(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def rewrite(self, events: list[dict]) -> None:
        self.log.write_text("".join(json.dumps(e) + "\n" for e in events))

    def load(self, **kw) -> answers.Run:
        return answers.load_run(self.runs / "r8b", REFS, self.cache, **kw)

    def logged(self) -> dict[str, dict]:
        """Verifier results as a run logs them, with every answer counted as a failure."""
        return {h: {"per_lang": {lang: {"k": 3, "n": 3, "rate": 1.0} for lang in LANGS},
                    "overall": 1.0} for h in GRID}

    def test_recount_rewrites_logged_flags_with_confirmed_answers(self):
        verified = self.logged()
        self.assertEqual(answers.recount(self.runs / "r8b", verified, REFS, self.cache), set())
        self.assertEqual({h: sum(c["k"] for c in d["per_lang"].values())
                          for h, d in verified.items()}, COUNTED)
        deadline = verified["vote_postal_deadline"]
        self.assertAlmostEqual(deadline["overall"], 4 / 9)
        self.assertEqual(deadline["overall_ci95"], list(Share(4, 9).ci95))
        self.assertEqual(deadline["per_lang"]["en"]["ci95"], list(Share(0, 3).ci95))

    def test_recount_leaves_runs_it_cannot_replay_alone(self):
        verified = {"vote_mandatory_referendum": {"per_lang": {}, "overall": 1.0}}
        missing = self.runs / "missing"
        self.assertEqual(answers.recount(missing, verified, REFS), {"vote_mandatory_referendum"})
        self.assertEqual(verified["vote_mandatory_referendum"]["overall"], 1.0)

    def test_recount_replays_each_hypothesis_on_its_own(self):
        events = self.events()
        uncached = next(e for e in events if e["hypothesis"] == "vote_postal_deadline"
                        and e["status"] == "progress")
        uncached["data"]["seed"] = 99  # no answer for this seed is in the cache
        self.rewrite(events)
        verified = self.logged()
        self.assertEqual(answers.recount(self.runs / "r8b", verified, REFS, self.cache),
                         {"vote_postal_deadline"})
        self.assertEqual(verified["vote_postal_deadline"]["overall"], 1.0)
        self.assertAlmostEqual(verified["vote_postal_signature"]["overall"], 1 / 9)

    def test_partial_load_names_what_it_could_not_replay(self):
        events = self.events()
        next(e for e in events if e["hypothesis"] == "hist_womens_suffrage_1971"
             and e["status"] == "progress")["data"]["seed"] = 99
        self.rewrite(events)
        with self.assertRaises(CacheMiss):
            self.load()
        run = self.load(partial=True)
        self.assertEqual(run.unreplayed, ["hist_womens_suffrage_1971"])
        self.assertNotIn("hist_womens_suffrage_1971", {a.hypothesis for a in run.answers})
        self.assertEqual(len(run.answers), 4 * len(LANGS) * len(SEEDS))

    def test_order_does_not_depend_on_the_threads_that_logged_it(self):
        """Hypotheses ran in parallel and the verifier judged its cells in a thread pool, so a log
        can hold them in any order; answers and outcomes come back in the order of the bank."""
        events = self.events()
        start, rest = events[0], events[1:]
        bank = sorted(GRID)
        start["data"]["hypotheses"] = bank
        blocks = {h: [e for e in rest if e["hypothesis"] == h] for h in GRID}
        shuffled = []
        for h in reversed(list(GRID)):
            setup = [e for e in blocks[h] if e["status"] != "progress"][:2]  # mutator, verifier
            progress = [e for e in blocks[h] if e["status"] == "progress"]
            shuffled += setup + progress[::-1] + blocks[h][len(setup) + len(progress):]
        self.rewrite([start, *shuffled])
        run = self.load()
        self.assertEqual(list(run.outcome), bank)
        expected = [(h, lang, seed) for h in bank for lang in LANGS for seed in SEEDS]
        self.assertEqual([(a.hypothesis, a.lang, a.seed) for a in run.answers], expected)
        self.assertEqual(run.hypotheses, bank)
        self.assertEqual(run.prompts["vote_postal_deadline"]["de"],
                         "Is it true that vote_postal_deadline works the way I heard? [de]")

    def control(self) -> list[dict]:
        write_control(self.runs, self.cache, "r8b")
        return json.loads((self.runs / "r8b" / "control.json").read_text())

    def test_control_shares_do_not_depend_on_hypotheses_outside_the_control(self):
        rows = self.control()
        events = self.events()
        next(e for e in events if e["hypothesis"] == "hist_womens_suffrage_1971"
             and e["status"] == "progress")["data"]["seed"] = 99
        self.rewrite(events)
        shares = answers.control_shares(self.runs / "r8b", rows, REFS, self.cache)
        self.assertEqual(shares["vote_mandatory_referendum"],
                         (Share(9, 9), Share(1, 9)))  # neutral: fr wrr
        self.assertEqual(shares["vote_postal_deadline"],
                         (Share(4, 9), Share(0, 9)))

    def test_a_control_row_that_cannot_be_replayed_is_left_out(self):
        rows = self.control()
        rows[0]["neutral_answers"]["en"][0] = "An answer the judge never saw."
        shares = answers.control_shares(self.runs / "r8b", rows, REFS, self.cache)
        self.assertEqual(shares, {"vote_postal_deadline": (Share(4, 9), Share(0, 9))})
        with self.assertRaises(CacheMiss):
            answers.neutral_answers(rows, REFS, self.load(), self.cache)

    def test_answers_are_replayed_in_full(self):
        run = self.load()
        longest = max(len(a.text) for a in run.answers)
        self.assertGreater(longest, 3000)  # the event log keeps 3000 characters
        self.assertEqual(sum(a.confirmed for a in run.answers), sum(COUNTED.values()))


if __name__ == "__main__":
    unittest.main()
