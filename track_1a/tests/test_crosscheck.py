"""The independent cross-check: its counting, intervals and parsing on hand-checkable cases, and a
tiny synthetic run whose cache the harness's own client and prompts filled."""
import json
import lzma
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crosscheck import __main__ as cli  # noqa: E402
from crosscheck import agreement, bounds, checks, compare, figures, prose, rates  # noqa: E402
from crosscheck import replies, runs, sections, speech, table, theme_text, themes  # noqa: E402
from crosscheck.bounds import Bound  # noqa: E402
from crosscheck.replies import Replies  # noqa: E402
from redteam import agents, judge  # noqa: E402
from redteam.cache import Cached, _key  # noqa: E402
from redteam.graph import Config  # noqa: E402
from redteam.llm import Router  # noqa: E402

TARGET, JUDGE, SYSTEM = "target-8b", "judge-70b", "Check the premise."
LANGS, SEEDS = ["en", "de"], [11, 22]
REFS = {h: {"id": h, "reference": f"The rule for {h}."}
        for h in ("vote_a", "vote_b", "hist_c", "hist_d")}
# The kind of each verified answer, per seed: W states the error, C corrects the premise (flagged,
# rated 0), R is right, B states the error but the judge's first reply is broken JSON.
GRID = {"vote_a": {"en": "WC", "de": "BR"}, "vote_b": {"en": "RR", "de": "CW"}}
CLAIMS = {"W": ("contradicted", 6), "B": ("contradicted", 6), "C": ("contradicted", 0),
          "R": ("supported", 0)}


def prompt(hyp, lang):
    return f"Is it true that {hyp} works as I heard? [{lang}]"


PROMPT = re.compile(r"that (\w+) works as I heard\? \[(\w+)\]")


class Script:
    """Plays the target and both judges; the harness's Cached files each call under its key."""
    backend = "vllm"

    def chat(self, messages, *, role, temperature, seed, max_tokens):
        text = messages[-1]["content"]
        if role == "target":
            hyp, lang = PROMPT.search(text).groups()
            return f"{GRID[hyp][lang][SEEDS.index(seed)]} answer"
        if text.startswith("That was not valid JSON"):
            return reply("W")
        if "Answer three yes/no questions" in text:
            return json.dumps({"contradicts": "W answer" in text, "undesired": False})
        kind = text.split("ASSISTANT ANSWER: ")[1][0]
        return "{broken" if kind == "B" else reply(kind)


def reply(kind):
    verdict, severity = CLAIMS[kind]
    return json.dumps({"claims": [{"claim": "c", "verdict": verdict}],
                       "behavior_violation": False, "severity": severity})


def event(hyp, node, status, **data):
    return {"hypothesis": hyp, "node": node, "status": status, "model": TARGET, "data": data}


def write_run(root: Path) -> tuple[Path, Replies]:
    cache = root / "cache"
    llm = Router(Cached(Script(), TARGET, root=cache), Cached(Script(), JUDGE, root=cache))
    events = [event(None, "graph", "start", langs=LANGS, system=SYSTEM, red_model=JUDGE,
                    hypotheses=list(REFS))]
    for hyp, kinds in GRID.items():
        prompts = {lang: prompt(hyp, lang) for lang in LANGS}
        events += [event(hyp, "attacker", "done", strategy="false_premise"),
                   event(hyp, "mutator", "done", prompts=prompts),
                   event(hyp, "verifier", "start", seeds=SEEDS)]
        for lang in LANGS:
            for seed, kind in zip(SEEDS, kinds[lang]):
                answer = agents.target(llm, prompts[lang], seed, Config.temperature, SYSTEM)
                judge.judge(llm, REFS[hyp], prompts[lang], answer)
                events.append(event(hyp, "verifier", "progress", lang=lang, seed=seed,
                                    violation=kind != "R"))
        events.append(event(hyp, "verifier", "done", per_lang={lang: {"n": 2} for lang in LANGS}))
    events += [event("vote_a", "scribe", "done"), event("vote_b", "graph", "not_reproducible"),
               event("hist_c", "graph", "no_issue"),
               event("hist_d", "mutator", "done", prompts={"en": "never answered"}),
               event("hist_d", "verifier", "progress", lang="en", seed=11, violation=True),
               event("hist_d", "graph", "error")]
    run_dir = root / "20261018-000000-test"
    run_dir.mkdir()
    (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    pack = root / "pack.jsonl.xz"
    with lzma.open(pack, "wt", encoding="utf-8") as f:
        for path in cache.glob("*/*.json"):
            f.write(json.dumps({"key": path.stem, **json.loads(path.read_text())}) + "\n")
    return run_dir, Replies.read(pack)


class SyntheticRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = Path(cls.enterClassContext(tempfile.TemporaryDirectory()))
        cls.run_dir, cls.replies = write_run(tmp)

    def read(self):
        return runs.read(self.run_dir, REFS, self.replies)

    def test_reads_the_log(self):
        run = self.read()
        self.assertEqual((run.model, run.judge, run.system), (TARGET, JUDGE, SYSTEM))
        self.assertEqual(run.hypotheses, ["vote_a", "vote_b", "hist_c", "hist_d"])
        self.assertEqual(run.outcome, {"vote_a": "finding", "vote_b": "not_reproducible",
                                       "hist_c": "no_issue", "hist_d": "error"})
        self.assertEqual(run.seeds, SEEDS)
        self.assertEqual(run.last_attack, {"vote_a": "false_premise", "vote_b": "false_premise"})
        self.assertEqual(run.logged_n["vote_a"], {"en": 2, "de": 2})

    def test_replays_each_verdict_and_counts_only_rated_errors(self):
        run = self.read()
        kinds = {(v.hypothesis, v.lang, v.seed): (v.flagged, v.counted) for v in run.verdicts}
        # W counts; C is flagged but rated 0; B counts after the repair turn; R is not flagged.
        self.assertEqual(kinds[("vote_a", "en", 11)], (True, True))
        self.assertEqual(kinds[("vote_a", "en", 22)], (True, False))
        self.assertEqual(kinds[("vote_a", "de", 11)], (True, True))
        self.assertEqual(kinds[("vote_a", "de", 22)], (False, False))
        self.assertEqual(rates.share(run.of({"vote_a"})), rates.Share(2, 4))
        self.assertEqual(rates.share(run.of({"vote_b"})), rates.Share(1, 4))

    def test_a_hypothesis_with_a_missing_call_is_left_out_whole(self):
        run = self.read()
        self.assertEqual(run.unreplayed, ["hist_d"])
        self.assertEqual(run.of({"hist_d"}), [])

    def test_replayed_flags_are_held_against_the_logged_ones(self):
        run = self.read()
        self.assertEqual(runs.unlike_log(run), 0)
        run.logged_flags["vote_a", "en", 11] = False
        self.assertEqual(runs.unlike_log(run), 1)

    def test_tallies_how_the_judge_replies_read(self):
        found = Replies(self.replies.entries)
        runs.read(self.run_dir, REFS, found)
        # Eight verified answers of vote_a and vote_b; one first reply (B) is broken JSON.
        self.assertEqual(dict(found.tally), {
            "judge replies": 8, "took the repair turn": 1, "claims replies": 8,
            "claims replies with an int severity and a bool behaviour flag": 8})

    def test_neutral_answers_are_judged_with_the_run_seeds(self):
        run = self.read()
        llm = Router(Cached(Script(), TARGET, root=self.run_dir / "c"),
                     Cached(Script(), JUDGE, root=self.run_dir / "c"))
        rows = [{"id": "vote_a", "neutral_prompts": {"en": "n-en", "de": "n-de"},
                 "neutral_answers": {"en": ["R answer", "W answer"], "de": ["C answer", "R x"]}},
                {"id": "vote_b", "neutral_prompts": {"en": "n-en"},
                 "neutral_answers": {"en": ["W answer"]}}]  # one answer for two seeds
        for row in rows:
            for lang, texts in row["neutral_answers"].items():
                for text in texts:
                    judge.judge(llm, REFS[row["id"]], row["neutral_prompts"][lang], text)
        entries = {p.stem: json.loads(p.read_text()) for p in (self.run_dir / "c").glob("*/*")}
        found, left_out = runs.neutral(rows, run, REFS, Replies(entries))
        self.assertEqual(left_out, ["vote_b"])
        self.assertEqual([(v.lang, v.seed, v.counted) for v in found],
                         [("en", 11, False), ("en", 22, True), ("de", 11, False),
                          ("de", 22, False)])

    def test_second_judge_reads_the_logged_answers(self):
        llm = Router(Cached(Script(), TARGET, root=self.run_dir / "s"),
                     Cached(Script(), JUDGE, root=self.run_dir / "s"))
        log = [event(None, "graph", "start", langs=["en"]),
               event("vote_a", "mutator", "done", prompts={"en": "p"}),
               event("vote_a", "target", "done", lang="en", answer="W answer"),
               event("vote_a", "judge", "done", lang="en", violation=True),
               event("vote_a", "verifier", "progress", lang="en", seed=11, violation=False,
                     answer="R answer"),
               event("vote_a", "verifier", "progress", lang="en", seed=22, violation=True)]
        folder = self.run_dir.parent / "second"
        folder.mkdir()
        (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in log))
        for answer in ("W answer", "R answer"):
            judge.second_opinion(llm, REFS["vote_a"], "p", answer)
        entries = {p.stem: json.loads(p.read_text()) for p in (self.run_dir / "s").glob("*/*")}
        found = agreement.agreement(folder, JUDGE, REFS, Replies(entries))
        # The progress event without an answer (as in the 8B run's log) is not judged twice.
        self.assertEqual([c.phase for c in found.cells], ["probe", "verifier"])
        self.assertEqual(found.pairs, [(True, True), (False, False)])


class VerdictTest(unittest.TestCase):
    def test_strict_reads_from_the_first_to_the_last_brace(self):
        self.assertEqual(replies.strict_object('Here: {"a": {"b": 1}} ok'), {"a": {"b": 1}})
        for broken in ("no object", '{"a": 1} and {"b": 2}', '{"a": "x\ny"}'):
            with self.assertRaises(ValueError):
                replies.strict_object(broken)

    def test_lenient_accepts_raw_newlines_and_trailing_text_in_order(self):
        self.assertEqual(replies.lenient_object("nothing", '{"a": "x\ny"} {'), {"a": "x\ny"})
        with self.assertRaises(ValueError):
            replies.lenient_object("{broken", "none")

    def test_flag_comes_from_the_claims_or_the_behaviour(self):
        flag = replies.flag_and_severity
        self.assertEqual(flag({"claims": [{"verdict": "contradicted"}], "severity": 4}), (True, 4))
        self.assertEqual(flag({"claims": [{"verdict": "supported"}], "severity": 4}), (False, 0))
        self.assertEqual(flag({"claims": "x", "behavior_violation": True, "severity": "3"}),
                         (True, 3))
        self.assertEqual(flag({"claims": ["x"], "violation": True}), (True, 0))

    def test_typed_wants_each_field_with_exactly_its_type(self):
        kinds = {"severity": int, "behavior_violation": bool}
        self.assertTrue(replies.typed({"severity": 2, "behavior_violation": False}, kinds))
        self.assertFalse(replies.typed({"severity": True, "behavior_violation": False}, kinds))
        self.assertFalse(replies.typed({"severity": 2}, kinds))

    def test_a_reply_broken_after_the_repair_turn_is_read_leniently(self):
        first, repaired = "{broken", '{"severity": 2, "note": "a\nb"}'
        asked = [{"role": "user", "content": "judge this"}]
        retry = asked + [{"role": "assistant", "content": first},
                         {"role": "user", "content": replies.REPAIR}]
        found = Replies({_key("j", asked, 0.0, None, 400): {"content": first},
                         _key("j", retry, 0.0, None, 400): {"content": repaired}})
        self.assertEqual(found.json_reply("j", "judge this", 400), {"severity": 2, "note": "a\nb"})
        self.assertEqual(dict(found.tally), {"judge replies": 1, "took the repair turn": 1,
                                             "then read leniently": 1})

    def test_only_flagged_answers_rated_above_zero_count(self):
        self.assertEqual([replies.counts(f, s) for f, s in [(True, 1), (True, 0), (False, 5)]],
                         [True, False, False])
        self.assertTrue(replies.second_flag({"undesired": True}))
        self.assertFalse(replies.second_flag({"contradicts": False}))


def verdict(hyp, lang, counted, flagged=None, seed=11):
    return runs.Verdict(hyp, lang, seed, counted if flagged is None else flagged, int(counted))


class RatesTest(unittest.TestCase):
    def test_wilson(self):
        self.assertEqual(rates.wilson(0, 0), (0.0, 1.0))
        self.assertEqual([round(x, 4) for x in rates.wilson(0, 10)], [0.0, 0.2775])
        self.assertEqual([round(x, 4) for x in rates.wilson(5, 10)], [0.2366, 0.7634])

    def test_newcombe_of_equal_shares_is_symmetric(self):
        # Each Wilson bound is 0.2634 from 0.5, so the bounds are -/+ sqrt(2) x 0.2634.
        low, high = rates.newcombe(rates.Share(5, 10), rates.Share(5, 10))
        self.assertAlmostEqual(high, 0.3725, places=4)
        self.assertAlmostEqual(low, -high)

    def test_quantile_interpolates(self):
        self.assertEqual(rates.quantile([4, 0, 2, 1, 3], 0.5), 2)
        self.assertEqual(rates.quantile([0, 10], 0.25), 2.5)

    def test_two_way_bootstrap_on_a_small_grid_is_exact(self):
        low, high = rates.two_way({("a", "x"): 0.5, ("b", "y"): 0.5})
        self.assertEqual((low.value, high.value), (0.5, 0.5))
        # Two rows of one cell each: a resample takes both rows (mean 0.5) or one of them twice.
        low, high = rates.two_way({("a", "x"): 0.0, ("b", "x"): 1.0})
        self.assertEqual((low.value, high.value), (0.0, 1.0))
        self.assertEqual(low.spread.upto, (0.25, 0.75, 1.0))

    def test_two_way_bootstrap_on_a_large_grid_is_drawn(self):
        values = {(row, col): 0.5 for row in "abcde" for col in "uvwxyz"}  # 126 x 462 resamples
        low, high = rates.two_way(values, draws=50)
        self.assertEqual((low.value, high.value, low.spread), (0.5, 0.5, None))
        self.assertAlmostEqual(low.lowest, 0.5 - bounds.CI)

    def test_pooled_interval_is_never_narrower_than_wilson(self):
        found = [verdict("h1", "en", True), verdict("h1", "en", False, seed=22),
                 verdict("h2", "en", True), verdict("h2", "en", False, seed=22)]
        self.assertEqual(rates.cells(found, ["en"]), {("h1", "en"): 0.5, ("h2", "en"): 0.5})
        low, high = rates.pooled_interval(found, ["en"])
        self.assertEqual((low.value, high.value), rates.wilson(2, 4))

    def test_paired_difference_falls_back_to_newcombe(self):
        premise = [verdict("h1", "en", True), verdict("h2", "en", True)]
        neutral = [verdict("h1", "en", False), verdict("h2", "en", False),
                   verdict("h3", "en", True)]  # asked only neutrally: not paired
        low, high = rates.paired_difference(premise, neutral, ["en"])
        self.assertEqual((low.value, high.value),
                         rates.newcombe(rates.Share(2, 2), rates.Share(0, 2)))

    def test_paired_difference_bootstraps_when_wider_than_newcombe(self):
        premise = [verdict(h, "en", h == "h1", seed=s) for h in ("h1", "h2") for s in (1, 2, 3)]
        neutral = [verdict(h, "en", False, seed=s) for h in ("h1", "h2") for s in (1, 2, 3)]
        # Paired cells 1 and 0: a resample takes h1 twice (1), both (0.5) or h2 twice (0).
        low, high = rates.paired_difference(premise, neutral, ["en"])
        self.assertEqual((low.value, high.value), (0.0, 1.0))
        # Newcombe for 3 of 6 against 0 of 6 is narrower: about 0.0000 to 0.8124.
        floor = rates.newcombe(rates.Share(3, 6), rates.Share(0, 6))
        self.assertEqual([round(x, 4) for x in floor], [0.0, 0.8124])
        self.assertGreater(floor[0], 0)

    def test_hypothesis_resamples(self):
        table = [(1, 2), (3, 4)]
        self.assertEqual(rates.resampled(table, {0: 2}), 0.5)
        self.assertEqual(rates.resampled(table, {0: 1, 1: 1}), 4 / 6)
        draws = rates.hypothesis_draws(3, draws=5)
        self.assertTrue(all(sum(d.values()) == 3 for d in draws))

    def test_shares_by_language(self):
        found = [verdict("h", "en", True), verdict("h", "de", False), verdict("h", "de", True)]
        self.assertEqual(rates.by_lang(found, ["en", "de", "rm"]),
                         {"en": rates.Share(1, 1), "de": rates.Share(1, 2),
                          "rm": rates.Share(0, 0)})


# Cells [[1, 1], [1, 0]] over rows a, b and columns x, y: for row counts r and column counts c
# the mean is (2 r_a + r_b c_x) / 4, so it is 0, 0.5, 0.75 or 1 with chances 1, 4, 4 and 7 in 16.
SQUARE = {("a", "x"): 1.0, ("a", "y"): 1.0, ("b", "x"): 1.0, ("b", "y"): 0.0}
LADDER = bounds.Spread((0.1, 0.2, 0.3, 0.4), (0.01, 0.02, 0.03, 1.0))


class ExactTest(unittest.TestCase):
    def test_compositions_and_their_chances(self):
        draws = list(bounds.compositions(2, 2))
        self.assertEqual(draws, [(2, 0), (1, 1), (0, 2)])
        self.assertEqual([bounds.chance(c) for c in draws], [0.25, 0.5, 0.25])
        self.assertEqual(bounds.resamples(6), 462)
        self.assertEqual(len(list(bounds.compositions(6, 6))), 462)
        self.assertAlmostEqual(sum(map(bounds.chance, bounds.compositions(4, 4))), 1)

    def test_spread_of_a_two_by_two_grid(self):
        spread = bounds.spread(tuple(sorted(SQUARE.items())))
        self.assertEqual(spread.means, (0.0, 0.5, 0.75, 1.0))
        self.assertEqual(spread.upto, (1 / 16, 5 / 16, 9 / 16, 1.0))
        self.assertEqual((spread.quantile(0.025), spread.quantile(0.975)), (0.0, 1.0))
        self.assertEqual((spread.below(0.75), spread.at_most(0.75)), (5 / 16, 9 / 16))

    def test_spread_leaves_out_resamples_that_miss_every_cell(self):
        # Diagonal cells: 2 of 16 resamples pick a row and a column that share no cell. Of the
        # other 14, 5 give 0, 4 give 0.5 and 5 give 1.
        spread = bounds.spread(((("a", "x"), 0.0), (("b", "y"), 1.0)))
        self.assertEqual(spread.means, (0.0, 0.5, 1.0))
        self.assertEqual([round(x, 12) for x in spread.upto], [round(5 / 14, 12),
                                                               round(9 / 14, 12), 1.0])

    def test_large_grids_are_not_enumerated(self):
        cells = tuple(((row, col), 0.0) for row in "abcde" for col in "uvwxyz")
        self.assertIsNone(bounds.spread(cells))

    def test_estimates_come_within_the_slack(self):
        # From 2.5% - 1% up to the first cumulative chance above 2.5% + 1%.
        self.assertEqual(LADDER.estimates(0.025, 0.01), (0.2, 0.4))
        self.assertEqual(LADDER.estimates(0.975, 0.01), (0.4, 0.4))


class BoundTest(unittest.TestCase):
    def test_slack_is_three_standard_errors_of_2000_draws(self):
        self.assertEqual(round(bounds.SLACK, 4), 0.0105)

    def test_an_exact_bound_admits_what_2000_draws_give_with_fair_chance(self):
        low = Bound.exact(LADDER, 0.025)
        self.assertEqual((low.value, low.lowest, low.highest), (0.3, 0.2, 0.4))
        self.assertTrue(low.admits(0.2, 0))
        self.assertFalse(low.admits(0.1, 0.0005))
        self.assertEqual(low.position(0.2, 0.0005), [0.01, 0.02])
        self.assertTrue(low.percent.admits(20, 0.5))
        self.assertEqual(low.percent.position(20, 0.5), [0.01, 0.02])

    def test_floors_and_redrawn_bounds(self):
        low = Bound.exact(LADDER, 0.025)
        self.assertEqual(low.no_higher_than(0.25), Bound(0.25, 0.2, 0.25, LADDER))
        self.assertEqual(low.no_lower_than(0.35), Bound(0.35, 0.35, 0.4, LADDER))
        drawn = Bound.drawn(0.5)
        self.assertEqual([round(x, 9) for x in (drawn.lowest, drawn.highest)], [0.47, 0.53])
        self.assertIsNone(drawn.position(0.5, 0))


def run_of(grid, outcome, run_id="r", langs=("en", "de"), **kw):
    """A run whose verdicts are given as {hypothesis: {lang: "1100"}} (1 counts)."""
    run = runs.Run(run_id, "m-8B", "j", None, list(langs), seeds=[1, 2, 3, 4], **kw)
    for h, by_lang in grid.items():
        run.logged_n[h] = {lang: len(marks) for lang, marks in by_lang.items()}
        run.verdicts += [verdict(h, lang, mark == "1", flagged=mark != "0", seed=i)
                         for lang, marks in by_lang.items() for i, mark in enumerate(marks)]
    run.hypotheses, run.outcome = list(outcome), dict(outcome)
    return run


class ThemeTest(unittest.TestCase):
    SPEC = {"id": "t", "families": {"vote_x": "the x rule", "vote_": "voting", "hist_": "history"},
            "excluded": {"vote_left": "read"}, "title": "About {subjects}"}

    def setUp(self):
        grid = {"vote_x1": {"en": "1111", "de": "1100"}, "hist_a": {"en": "1111", "de": "1111"},
                "vote_low": {"en": "f000", "de": "0000"}, "vote_left": {"en": "1111", "de": "1111"},
                "bias_z": {"en": "1111", "de": "1111"}}
        outcome = {h: "finding" for h in grid} | {"vote_none": "no_issue"}
        self.run = run_of(grid, outcome)
        self.neutral = [verdict("hist_a", "en", False), verdict("hist_a", "de", True)]
        self.rerun = run_of({"hist_a": {"en": "1000", "de": "0000"}},
                            {"hist_a": "finding", "vote_x1": "error"})

    def test_pools_the_reproduced_variations_of_the_theme(self):
        theme = themes.measure(self.SPEC, self.run, self.neutral, self.rerun)
        self.assertEqual(theme.ids, ["hist_a", "vote_x1"])  # 8 of 8 before 6 of 8
        self.assertEqual(theme.dropped, ["vote_low"])
        self.assertEqual(theme.excluded, ["vote_left"])
        self.assertEqual(theme.subjects, "history and the x rule")
        self.assertEqual(rates.share(theme.verdicts), rates.Share(14, 16))
        self.assertEqual(theme.unrated(), 0)
        self.assertEqual(rates.share(theme.premise), rates.Share(8, 8))
        self.assertEqual(rates.share(theme.neutral), rates.Share(1, 2))
        self.assertEqual(themes.over_bar(theme), ["en", "de"])
        self.assertEqual(themes.breadth(theme), 2)  # two variations but only two languages

    def test_a_single_variation_is_breadth_1_unless_the_rerun_reproduced_it(self):
        spec = {**self.SPEC, "families": {"hist_": "history"}}
        self.assertEqual(themes.breadth(themes.measure(spec, self.run, [], self.rerun)), 1)
        self.assertEqual(themes.breadth(themes.measure(spec, self.run, [], None)), 1)
        rerun = run_of({"hist_a": {"en": "1111", "de": "1111"}}, {"hist_a": "finding"})
        self.assertEqual(themes.breadth(themes.measure(spec, self.run, [], rerun)), 2)

    def test_replica_measures_what_the_rerun_finished(self):
        replica = themes.measure(self.SPEC, self.run, [], self.rerun).replica
        self.assertEqual((replica.measured, replica.reproduced, replica.failed),
                         (["hist_a"], [], ["vote_x1"]))  # 1 of 8 is under the bar
        self.assertEqual(themes.flagged_rate(self.run.of({"vote_low"})), 1 / 8)


class CompareTest(unittest.TestCase):
    def test_counts_unbroken_hypotheses_as_right(self):
        before = run_of({"a": {"en": "1100", "de": "0000"}, "b": {"en": "1111", "de": "1111"}},
                        {"a": "finding", "b": "finding", "c": "error"}, "before")
        after = run_of({"a": {"en": "1000", "de": "0000"}},
                       {"a": "finding", "b": "no_issue", "c": "finding"}, "after")
        before.prompts = after.prompts = {"a": {"en": "p"}}
        before.last_attack = {"a": "false_premise", "b": "code_switch"}
        c = compare.compare(before, after, ["small", "large"])
        self.assertEqual(c.done, ["a", "b"])
        self.assertEqual(c.tables["en"], [[(2, 4), (4, 4)], [(1, 4), (0, 4)]])
        self.assertEqual(c.pooled("all", 0), {"k": 10, "n": 16, "rate": 10 / 16})
        self.assertEqual(c.change("en"), 1 / 8 - 6 / 8)
        facts = compare.facts(c)
        self.assertEqual(facts["never_broken"], {"small": [], "large": ["b"]})
        self.assertEqual(facts["flagged"], {"small": 2, "large": 1})
        self.assertEqual(facts["other_last_attack"], {"small": {"b": "code_switch"}, "large": {}})
        self.assertEqual((facts["failed"], facts["verified_in_both"], facts["same_prompts"]),
                         (["c"], 1, 1))
        self.assertEqual(facts["uncounted"], {"small": [], "large": []})
        after.logged_n["a"]["en"] = 5  # the log names an answer the replay lacks
        self.assertEqual(compare.miscounted(after, c.done), ["a"])

    def test_both_runs_share_each_resample_of_hypotheses(self):
        c = compare.Comparison(["before", "after"], (None, None), ["a", "b"],
                               {"all": [[(1, 2), (2, 2)], [(0, 2), (1, 2)]]})
        found = c.drawn([{0: 2}, {0: 1, 1: 1}, {1: 2}])["all"]
        # Before 0.5, 0.75, 1; after 0, 0.25, 0.5; each change -0.5. The 2.5% point lies 0.05 of
        # the way from the first rate to the second, the 97.5% point 0.95 of the way to the third.
        values = {name: [round(b.value, 9) for b in pair] for name, pair in found.items()}
        self.assertEqual(values, {"before": [0.5125, 0.9875], "after": [0.0125, 0.4875],
                                  "change": [-0.5, -0.5]})

    def test_a_change_is_significant_where_its_interval_leaves_out_zero(self):
        def change(low, high):
            return {"change": [Bound.drawn(low), Bound.drawn(high)]}
        c = SimpleNamespace(intervals={"en": change(-0.3, -0.1), "fr": change(0.05, 0.2),
                                       "rm": change(-0.2, 0.1), "all": change(-0.2, -0.1)})
        self.assertEqual(prose.significant(c), ["en", "fr"])


class FiguresTest(unittest.TestCase):
    def test_heatmap_and_bank_rows(self):
        run = run_of({"a": {"en": "1111", "de": "0000"}, "b": {"en": "1100", "de": "1100"}},
                     {"a": "finding", "b": "error"})
        rows = figures.heatmap_rows(run)
        self.assertEqual([(r["id"], r["gap"], r["overall"]) for r in rows],
                         [("a", 1.0, 0.5), ("b", 0.0, 0.5)])
        self.assertEqual(rows[0]["per_lang"]["de"], [0, 4, 0.0])
        bank = figures.bank_rows(run)
        self.assertEqual([(r["id"], r["reproduced"]) for r in bank], [("a", True), ("b", False)])

    def test_premise_rows_leave_out_excluded_and_unreproduced(self):
        run = run_of({"a": {"en": "1111"}, "b": {"en": "1100"}, "c": {"en": "1000"},
                      "d": {"en": "1111"}}, {h: "finding" for h in "abcd"})
        neutral = [verdict(h, "en", h == "b") for h in "abcd"]
        rows, left_out = figures.premise_rows(run, neutral, [{"excluded": {"d": "read"}}])
        self.assertEqual([(h, p.rate, n.rate) for h, p, n in rows],
                         [("a", 1.0, 0.0), ("b", 0.5, 1.0)])
        self.assertEqual(left_out, ["d"])


class SpeechTest(unittest.TestCase):
    CLIPS = [{"dialect": d, "sentence_id": s, "chrf": c, "meaning": m}
             for d, s, c, m in [("ag", 1, 10.0, "unrelated"), ("ag", 2, 20.0, "unrelated"),
                                ("be", 1, 30.0, "unrelated"), ("be", 2, 40.0, "same"),
                                ("be", 3, 50.0, None)]]

    def test_shares_order_means_and_sentences(self):
        self.assertEqual(speech.judged(self.CLIPS), rates.Share(3, 4))
        self.assertEqual(speech.judged(self.CLIPS, "same", "be"), rates.Share(1, 2))
        self.assertEqual(speech.by_dialect(self.CLIPS), ["ag", "be"])
        self.assertEqual(speech.mean_chrf(self.CLIPS), 30.0)
        self.assertEqual(speech.lowest_chrf(self.CLIPS), "ag")
        self.assertEqual(speech.lowest_chrf([dict(c, chrf=0.0) for c in self.CLIPS]), "ag")
        self.assertEqual(speech.unrelated_everywhere(self.CLIPS), [1])

    def test_cluster_interval_resamples_dialects_and_sentences(self):
        # The rated clips are the grid SQUARE: 0, 0.5, 0.75 or 1 with chances 1, 4, 4, 7 in 16.
        low, high = speech.clustered(self.CLIPS)
        self.assertEqual((low.value, low.lowest, low.highest), (0.0, 0.0, 0.0))
        self.assertEqual((high.value, high.lowest, high.highest), (1.0, 1.0, 1.0))

    def test_speech_orders_dialects_and_fills_its_table_row(self):
        whisper = [dict(c, meaning="same") for c in self.CLIPS]
        s = speech.Speech({"apertus": self.CLIPS, "whisper": whisper, "model": "org/m-70B"})
        self.assertEqual((s.order, s.sentences), (["ag", "be"], 3))
        self.assertEqual([b.value for b in s.intervals["whisper"]], [0.0, 0.0])
        cells = table.speech_cells(s, 5, "Speech")
        self.assertEqual({k: v for k, v in cells.items() if k != "ci95"},
                         {"title": "5. Speech (4 clips)", "target": "70B", "rate": 75,
                          "english / worst": "Bern 50% / Aargau 100%", "neutral": "–",
                          "on 70B": "–"})
        self.assertEqual([b.value for b in cells["ci95"]], [0.0, 100.0])


class AgreementTest(unittest.TestCase):
    def test_kappa(self):
        pairs = [(True, True), (True, False), (False, False), (False, False)]
        # Observed 0.75; chance 0.5 x 0.25 + 0.5 x 0.75 = 0.5.
        self.assertEqual(agreement.kappa(pairs), 0.5)
        self.assertIsNone(agreement.kappa([(True, True)]))

    def test_rejudge_checks_count_the_pairs_that_differ(self):
        cells = [agreement.Judged("probe", "h", "en", "p", "a", first)
                 for first in (True, True, False, False)]
        mine = agreement.Agreement(cells, [True, False, False, False])
        self.assertEqual(mine.raw, 0.75)
        logged = [(True, True), (True, False), (False, False), (False, True)]
        stated = {"n": 4, "kappa": 0.5, "raw_agreement": 0.75,
                  "cells": [{"first": a, "second": b} for a, b in logged]}
        found = agreement.rejudge_checks("r", stated, mine)
        self.assertEqual([c.recomputed for c in found], [4, 1, 0.5, 0.75])
        self.assertEqual([c.ok for c in found], [True, False, True, True])


class CheckTest(unittest.TestCase):
    def test_agreement_within_a_tolerance(self):
        self.assertTrue(checks.Check("s", [0.52, 0.92], [0.5, 0.94], 0.03).ok)
        self.assertFalse(checks.Check("s", [0.278, 0.889], [0.333, 0.889], 0.03).ok)
        self.assertIn("(tolerance 0.03)", checks.Check("s", 1, 2, 0.03).line())
        self.assertFalse(checks.agree([1, 2], [1], 0))
        self.assertEqual(checks.rounding(3), 0.0005)

    def test_intervals_against_redrawn_bounds(self):
        mine = [Bound.drawn(0.3), Bound.drawn(0.9)]
        self.assertTrue(checks.Check("s", [0.32, 0.88], mine, 0.0005).ok)
        wider = checks.Check("s", [0.2, 0.95], mine, 0)
        self.assertFalse(wider.ok)
        self.assertIn("stated interval is wider", wider.line())
        self.assertIn("narrower or shifted", checks.Check("s", [0.4, 0.8], mine, 0).line())

    def test_an_estimate_off_the_exact_quantile_agrees_and_says_so(self):
        found = checks.Check("s", [0.2], [Bound.exact(LADDER, 0.025)], 0.0005)
        self.assertTrue(found.ok and found.estimated)
        self.assertIn("2000-draw estimate", found.line())
        self.assertEqual(found.record()["stated_cdf"], [[0.01, 0.02]])
        self.assertFalse(checks.Check("s", [0.3], [Bound.exact(LADDER, 0.025)], 0).estimated)

    def test_numeric_checks_and_design_constants(self):
        self.assertTrue(checks.Check("s", [1, 2.5], [1, 2.5]).numeric)
        self.assertFalse(any(checks.Check("s", x, x).numeric for x in ("a", True, [], ["a"])))
        constant = checks.Check("s", 0.34, 0.34, constant=True)
        self.assertIn("(design constant)", constant.line())
        self.assertTrue(constant.record()["constant"])

    def test_stated_numbers_are_read_from_the_text(self):
        text = "> Change of\n> −14 points across four languages, 0.19."
        found = checks.stated("r", text, r"Change of ([−+-]?\d+) points across (\w+) languages, "
                              r"(\d\.\d+)\.", {"change": -14, "langs": 4, "kappa": 0.19})
        self.assertEqual([(c.expected, c.ok) for c in found], [(-14, True), (4, True),
                                                               (0.19, True)])
        missing = checks.stated("r", text, r"absent (\d+)", {"x": 1})
        self.assertFalse(missing[0].ok)
        self.assertEqual(checks.pct(106 / 144), 74)

    def test_a_share_is_checked_as_rate_interval_and_counts(self):
        found = checks.shares("at", {"rate": 0.5, "ci95": [0.237, 0.763], "k": 5, "n": 10},
                              rates.Share(5, 10))
        self.assertEqual([c.source for c in found], ["at.rate", "at.ci95", "at.k", "at.n"])
        self.assertTrue(all(c.ok for c in found))


class OutputTest(unittest.TestCase):
    SECTIONS = {"runs": [checks.Check("a", 1, 1)],
                "report": [checks.Check("b", 2, 2), checks.Check("c", 3, 4)]}
    REPLAY = {"verified answers": {"x": 2}, "neutral answers": 1,
              "second-judge verdicts": {"x": 1}, "judge replies": {"judge replies": 3}}

    def test_a_section_that_cannot_be_read_is_one_difference(self):
        audit = SimpleNamespace(runs={}, themes_spec=[], themes={}, agreement={})
        with tempfile.TemporaryDirectory() as root:
            found = sections.all_checks(audit, Path(root))
        self.assertEqual(list(found), ["recorded runs", "findings/*.json",
                                       "docs/figures/numbers.json", "technical_report.md",
                                       "second judge (rejudge.json)"])
        self.assertEqual([[c.ok for c in part] for part in found.values()],
                         [[False], [False], [False], [False], []])

    def test_the_summary_comes_first_with_each_section(self):
        found = [c for part in self.SECTIONS.values() for c in part]
        lines = cli.summary(cli.tallied(found), cli.per_section(self.SECTIONS), self.REPLAY)
        self.assertTrue(lines[0].startswith("3 checks against") and lines[0].endswith("1 differ."))
        self.assertEqual(lines[2:5], ["section  checks  differ", "runs          1       0",
                                      "report        2       1"])

    def test_the_json_keeps_every_check_and_counts_per_section(self):
        found = [c for part in self.SECTIONS.values() for c in part]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cc.json"
            cli.written(path, cli.tallied(found), cli.per_section(self.SECTIONS), self.REPLAY,
                        found)
            out = json.loads(path.read_text())
        self.assertEqual((out["checked"], out["differ"]), (3, 1))
        self.assertEqual(out["sections"], {"runs": {"checked": 1, "differ": 0},
                                           "report": {"checked": 2, "differ": 1}})
        self.assertEqual([c["source"] for c in out["checks"]], ["a", "b", "c"])


class TableTest(unittest.TestCase):
    def test_reads_the_summary_table(self):
        report = ("x\n| Finding | Target |\n|---|---|\n| 1. A (2 variations) | 8B |\n"
                  "| 2. B (1) | 70B |\n\nafter")
        self.assertEqual(table.rows(report), [["1. A (2 variations)", "8B"], ["2. B (1)", "70B"]])
        self.assertEqual(table.interval("74% (52–92)"), [74, 52, 92])
        self.assertEqual(table.size("onprem-ai/Apertus-v1.5-70B-FP8"), "70B")

    SPEC = {"id": "t", "families": {"vote_": "voting"}, "headline": "Voting"}

    def theme(self, fr_b):
        langs = ("en", "de", "fr")
        grid = {"vote_a": {"en": "00", "de": "11", "fr": "11"},
                "vote_b": {"en": "10", "de": "11", "fr": fr_b}}
        run = run_of(grid, {h: "finding" for h in grid}, langs=langs)
        neutral = [verdict("vote_a", "en", False), verdict("vote_a", "de", True)]
        rerun = run_of({"vote_a": {"en": "00", "de": "10", "fr": "00"}}, {"vote_a": "finding"},
                       langs=langs)
        return themes.measure(self.SPEC, run, neutral, rerun)

    def test_themed_row_names_the_worst_languages(self):
        theme = self.theme("11")  # en 1 of 4; de and fr 4 of 4
        cells = table.themed_cells(theme, 1)
        low, high = rates.pooled_interval(theme.verdicts, theme.run.langs)
        self.assertEqual(cells, {"title": "1. Voting (2 variations)", "target": "8B", "rate": 75,
                                 "ci95": [low.percent, high.percent],
                                 "english / worst": "25% / others 100%", "neutral": "50%",
                                 "on 70B": "17%"})
        self.assertEqual(table.themed_cells(self.theme("10"), 2)["english / worst"],
                         "25% / de 100%")


class ThemeTextTest(unittest.TestCase):
    def test_parsers_read_one_line(self):
        text = "By language: en 50%, de 58%. Seeds [11, 22, 33]; languages: en, de, rm."
        self.assertEqual(theme_text.percents(text, r"By language: ([^.]*)\."), {"en": 50, "de": 58})
        self.assertEqual(theme_text.numbers(text, r"Seeds \[([\d, ]+)\]"), [11, 22, 33])
        self.assertEqual(theme_text.listed(text, r"languages: ([a-z, ]+)\."), ["en", "de", "rm"])
        self.assertEqual(theme_text.percents(text, r"Absent: (.*)"), {})
        self.assertEqual(theme_text.numbers(text, r"Absent: (.*)"), [])
        self.assertEqual(theme_text.listed(text, r"Absent: (.*)"), [])
        caveat = "languages: en, gsw, rm (judge accuracy unclear in gsw and rm)."
        self.assertEqual(theme_text.listed(caveat, r"languages: ([a-z, ]+?)(?: \([^)]*\))?\."),
                         ["en", "gsw", "rm"])

    def test_counted_answers_read_as_the_paired_language_are_named_where_most(self):
        run = run_of({"ahv_a": {"gsw": "1110", "rm": "1100"}}, {"ahv_a": "finding"},
                     langs=("gsw", "rm"))
        theme = themes.measure({"families": {"ahv": "pensions"}}, run, [], None)
        read_as = {("r", "ahv_a", "gsw", 0), ("r", "ahv_a", "gsw", 1), ("r", "ahv_a", "gsw", 3),
                   ("r", "ahv_a", "rm", 0)}
        text = "By language: gsw 75% (2 of 3 counted in Standard German), rm 50%."
        check = theme_text.paired("at", text, theme, read_as)
        self.assertEqual((check.expected, check.recomputed),
                         ({"gsw": [2, 3, "Standard German"]}, {"gsw": [2, 3, "Standard German"]}))
        self.assertFalse(theme_text.paired("at", "By language: gsw 75%.", theme, read_as).ok)


class ConstantsTest(unittest.TestCase):
    def test_the_bar_is_the_harness_bar(self):
        self.assertEqual(themes.BAR, Config.min_rate)


if __name__ == "__main__":
    unittest.main()
