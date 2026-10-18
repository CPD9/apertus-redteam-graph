import io
import json
import random
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from helpers import patch, premise, use_runs, write_run  # noqa: E402
from redteam import review, review_set  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

TRACK = Path(__file__).resolve().parents[1]
A, B = "20261001-000000-aaaa", "20261002-000000-bbbb"


def recorded_runs(test) -> Path:
    """Two runs of the helpers' grid as the set's 8B and 70B runs, with their cache, and label
    files that do not exist yet. Per language, of 15 answers the judge counts 9 (en), 10 (de) and
    8 (fr)."""
    d = tempfile.TemporaryDirectory()
    test.addCleanup(d.cleanup)
    root = Path(d.name)
    use_runs(test, root / "runs", root / "data-runs")
    for run_id in (A, B):
        write_run(root / "data-runs", root / "cache", run_id)
    patch(test, mock.patch.object(review_set, "RUNS", {A: "8B", B: "70B"}),
          mock.patch.object(review_set, "CACHE_DIR", root / "cache"),
          mock.patch.object(review, "LABELS", root / "labels" / "judge.jsonl"),
          mock.patch.object(review, "RATINGS", root / "labels" / "language.jsonl"))
    return root


def margins(quota: dict, *axes: int) -> set[int]:
    totals = Counter()
    for key, k in quota.items():
        totals[tuple(key[a] for a in axes)] += k
    return set(totals.values())


class KappaTest(unittest.TestCase):
    def test_perfect_agreement(self):
        self.assertEqual(review.cohen_kappa([(True, True), (False, False), (True, True)]), 1.0)

    def test_hand_computed(self):
        # 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no: po = .7, pe = .5*.6 + .5*.4 = .5, kappa = .4
        pairs = [(True, True)] * 20 + [(True, False)] * 5 + [(False, True)] * 10 + [(False, False)] * 15
        self.assertAlmostEqual(review.cohen_kappa(pairs), 0.4)

    def test_undefined(self):
        self.assertIsNone(review.cohen_kappa([]))
        self.assertIsNone(review.cohen_kappa([(False, False)] * 3))


class DesignTest(unittest.TestCase):
    def test_sixty_items_keep_every_margin_of_language_verdict_and_run_equal(self):
        cells = [((lang, counted, run), (i + j + k) % 2) for i, lang in enumerate("abcdef")
                 for j, counted in enumerate((True, False)) for k, run in enumerate("xy")]
        quota = review_set.quotas(cells, 60)
        self.assertEqual(sum(quota.values()), 60)
        self.assertEqual([margins(quota, 0), margins(quota, 1), margins(quota, 2)], [{10}, {30}, {30}])
        self.assertEqual([margins(quota, 0, 1), margins(quota, 1, 2)], [{5}, {15}])

    def test_other_hypotheses_come_before_a_second_answer_to_one(self):
        pool = [SimpleNamespace(hypothesis=h) for h in "aaaaabc"]
        picked = review_set.spread(pool, 3, random.Random(0))
        self.assertEqual(sorted(a.hypothesis for a in picked), ["a", "b", "c"])


class BlindSetTest(unittest.TestCase):
    def setUp(self):
        recorded_runs(self)

    def test_the_set_is_balanced_and_the_same_for_everyone(self):
        items = review_set.blind_set()
        self.assertEqual(len(items), 60)
        self.assertEqual(Counter(it["lang"] for it in items), {"en": 20, "de": 20, "fr": 20})
        self.assertEqual(Counter(it["judge_counts"] for it in items), {True: 30, False: 30})
        self.assertEqual(Counter(it["run_id"] for it in items), {A: 30, B: 30})
        self.assertEqual(review_set.blind_set(), items)
        other = review_set.blind_set(seed=1)
        self.assertNotEqual([it["id"] for it in other], [it["id"] for it in items])

    def test_nothing_sent_to_the_labeller_names_the_run_the_seed_or_the_verdict(self):
        shown = review.session("Ann")
        self.assertEqual(len(shown["items"]), 60)
        self.assertEqual({k for it in shown["items"] for k in review_set.HIDDEN if k in it}, set())
        self.assertFalse(any(run_id in json.dumps(shown) for run_id in (A, B)))
        self.assertTrue(all(len(it["id"]) == 12 and ":" not in it["id"] for it in shown["items"]))
        self.assertIsNone(shown["reveal"])

    def test_an_item_has_the_whole_answer_the_reference_and_the_english_question(self):
        it = next(it for it in review_set.blind_set() if it["judge_counts"] and it["lang"] == "de")
        self.assertGreater(len(it["answer"]), 3000)  # the event log keeps 3000 characters of it
        self.assertEqual(it["reference"], review_set.bank()[it["hypothesis"]]["reference"])
        self.assertEqual(it["english"], premise(it["hypothesis"], "en"))


class LabelTest(unittest.TestCase):
    def setUp(self):
        recorded_runs(self)
        self.items = review_set.blind_set()

    def test_a_later_label_replaces_an_earlier_one_and_the_file_keeps_no_verdict(self):
        first, second = self.items[:2]
        review.save_label("Ann", first["id"], "asserts")
        review.save_label("Ann", first["id"], "does_not", "on second reading", hedged=True)
        review.save_label("Ann", second["id"], "cant_tell")
        rows = {r["id"]: r for r in review.labels()}
        self.assertEqual(len(rows), 2)
        self.assertEqual(set(rows[first["id"]]),
                         {"labeller", "id", "human_violation", "hedged", "note", "at"})
        self.assertIsNone(rows[second["id"]]["human_violation"])
        joined = {r["id"]: r for r in review.judged(review.labels())}
        self.assertEqual((joined[first["id"]]["judge_violation"], joined[first["id"]]["run_id"]),
                         (first["judge_counts"], first["run_id"]))
        self.assertEqual(review.session("Ann")["done"][first["id"]],
                         {"label": "does_not", "note": "on second reading", "hedged": True})

    def test_the_verdicts_come_back_only_with_the_reveal_which_ends_labelling(self):
        it = self.items[0]
        review.save_label("  Ann ", it["id"], "asserts")
        self.assertIsNone(review.session("Ann")["reveal"])
        shown = review.reveal("Ann")
        self.assertEqual(shown["items"], [{"id": it["id"], "human_violation": True, "hedged": False,
                                           "judge_violation": it["judge_counts"],
                                           "judge_quote": it["judge_quote"]}])
        self.assertEqual(review.session("Ann")["reveal"], shown)
        with self.assertRaises(review.Closed):
            review.save_label("Ann", it["id"], "does_not")
        review.save_label("Ben", it["id"], "does_not")  # Ben has not seen them

    def test_bad_input_is_refused_and_nothing_is_written_until_someone_labels(self):
        review.session("Ann")
        good = self.items[0]["id"]
        for args in (("", good, "asserts"), ("x" * 41, good, "asserts"), ("Ann", "r:1", "asserts"),
                     ("Ann", good, "violation"), ("Ann", good, None), ("Ann", good, []),
                     ("Ann", good, {}), ("Ann", good, "asserts", ["note"]),
                     ("Ann", good, "asserts", "x" * 501), ("Ann", good, "asserts", "", "yes")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                review.save_label(*args)
        self.assertFalse(review.LABELS.exists())

    def test_the_dashboard_count_joins_page_rows_and_keeps_a_carried_verdict(self):
        review.save_label("Ann", self.items[0]["id"], "asserts")
        review.save_label("Ann", self.items[1]["id"], "cant_tell")
        with review.LABELS.open("a") as f:
            row = {"id": "x", "judge_violation": False, "human_violation": False}
            f.write(json.dumps(row) + "\n")
        verdict = self.items[0]["judge_counts"]
        self.assertEqual(review.agreement()["n"], 2)
        self.assertEqual(review.agreement()["agree"], 1 + (verdict is True))


class ReportTest(unittest.TestCase):
    def setUp(self):
        recorded_runs(self)
        self.cell = {}
        for it in review_set.blind_set():
            self.cell.setdefault((it["lang"], it["judge_counts"], it["run_id"]), it["id"])

    def label(self, name: str, lang: str, counted: bool, label: str, run=A, hedged=False):
        review.save_label(name, self.cell[lang, counted, run], label, hedged=hedged)

    def label_both(self):
        """Judge against people: en 3 of 3 agree, de 1 of 3, fr only "can't tell"."""
        for name, lang, counted, label in [
                ("Ann", "en", True, "asserts"), ("Ann", "de", True, "asserts"),
                ("Ann", "en", False, "does_not"), ("Ann", "de", False, "asserts"),
                ("Ben", "en", True, "asserts"), ("Ben", "de", True, "does_not"),
                ("Ben", "fr", True, "cant_tell")]:
            self.label(name, lang, counted, label)
        review.reveal("Ann")
        review.reveal("Ben")

    def test_without_labels_it_says_so(self):
        out = io.StringIO()
        with redirect_stdout(out):
            review.main()
        self.assertTrue(out.getvalue().startswith("No human labels yet."))
        self.assertIsNone(review.report()["judge_human"])

    def test_a_labeller_counts_against_the_judge_only_after_their_reveal(self):
        self.label("Ann", "en", True, "asserts")
        r = review.report()
        self.assertIsNone(r["judge_human"])
        self.assertNotIn("judge_accuracy", r)
        self.assertEqual([(w["name"], w["labels"], w["revealed_at"]) for w in r["labellers"]],
                         [("Ann", 1, None)])
        review.reveal("Ann")
        r = review.report()
        self.assertEqual(r["judge_human"]["per_labeller"]["Ann"]["n"], 1)
        self.assertIsNotNone(r["labellers"][0]["revealed_at"])

    def test_agreement_with_the_judge_overall_per_language_and_per_labeller(self):
        self.label_both()
        r = review.report()
        self.assertEqual(r["labels"], 7)
        self.assertEqual([(w["name"], w["labels"], w["cant_tell"]) for w in r["labellers"]],
                         [("Ann", 4, 0), ("Ben", 3, 1)])
        # 4 of 6 agree; judge and people both say yes 4 times in 6: pe = 20/36, kappa = .25
        everyone = r["judge_human"]["all"]
        self.assertEqual({k: everyone[k] for k in ("n", "agree", "raw_agreement", "kappa")},
                         {"n": 6, "agree": 4, "raw_agreement": 0.667, "kappa": 0.25})
        self.assertLess(everyone["ci95"][0], 0.667)
        self.assertGreater(everyone["ci95"][1], 0.667)
        self.assertEqual(len(everyone["kappa_ci95"]), 2)
        per_lang = r["judge_human"]["per_lang"]
        self.assertEqual([(per_lang[k]["agree"], per_lang[k]["n"]) for k in ("en", "de", "fr")],
                         [(3, 3), (1, 3), (0, 0)])
        people = r["judge_human"]["per_labeller"]
        self.assertEqual([(people[k]["agree"], people[k]["n"]) for k in ("Ann", "Ben")],
                         [(3, 4), (1, 2)])

    def test_agreement_between_two_labellers_on_the_items_both_labelled(self):
        self.label_both()
        (pair,) = review.report()["between_people"]
        keys = ("labellers", "n", "agree", "raw_agreement", "kappa")
        self.assertEqual({k: pair[k] for k in keys},
                         {"labellers": ["Ann", "Ben"], "n": 2, "agree": 1, "raw_agreement": 0.5,
                          "kappa": 0.0})

    def test_a_language_without_labels_on_both_verdicts_is_not_estimated(self):
        self.label_both()
        acc = review.report()["judge_accuracy"]["8B"]["codebook"]
        # en: counted all yes, not counted all no: (9*1 + 6*0)/15. de: the two counted labels
        # of one answer make 0.5, not counted yes: (10*0.5 + 5*1)/15.
        self.assertEqual((acc["rates"]["en"]["corrected"]["estimate"],
                          acc["rates"]["de"]["corrected"]["estimate"]), (0.6, 0.667))
        self.assertEqual(acc["rates"]["fr"], {"counted": 0.533, "corrected": {"estimate": None,
                                                                             "ci95": None}})
        self.assertIsNone(acc["rates"]["all"]["corrected"]["estimate"])
        self.assertIsNone(acc["sensitivity"]["estimate"])
        self.assertEqual(sorted(acc["missing"]), ["fr counted", "fr not counted"])
        self.assertEqual(acc["labelled"]["de"], {"counted": 1, "not_counted": 1})

    def test_sensitivity_specificity_and_corrected_rates_weight_labels_by_the_run(self):
        for lang, counted, label in [("en", True, "asserts"), ("en", False, "does_not"),
                                     ("de", True, "asserts"), ("de", False, "asserts"),
                                     ("fr", True, "does_not"), ("fr", False, "does_not")]:
            self.label("Ann", lang, counted, label)
        review.reveal("Ann")
        acc = review.report()["judge_accuracy"]
        run = acc["8B"]["codebook"]
        # tp 9 + 10, fn 5 (de not counted); tn 6 + 7, fp 8 (fr counted)
        self.assertEqual((run["sensitivity"]["estimate"], run["specificity"]["estimate"]),
                         (0.792, 0.619))
        self.assertEqual({k: v["corrected"]["estimate"] for k, v in run["rates"].items()},
                         {"en": 0.6, "de": 1.0, "fr": 0.0, "all": 0.533})
        self.assertEqual(run["rates"]["all"]["counted"], 0.6)
        for figure in (run["sensitivity"], run["specificity"], run["rates"]["all"]["corrected"]):
            low, high = figure["ci95"]
            self.assertLessEqual(low, figure["estimate"])
            self.assertGreaterEqual(high, figure["estimate"])
            self.assertLess(low, high)
        self.assertIsNone(acc["70B"]["codebook"]["sensitivity"]["estimate"])

    def test_hedged_answers_are_also_counted_the_judges_way(self):
        self.label("Ann", "en", True, "asserts", hedged=True)
        self.label("Ann", "de", True, "asserts")
        review.reveal("Ann")
        r = review.report()
        both = r["judge_human"]
        self.assertEqual((both["all"]["agree"], both["hedged_as_no"]["agree"]), (2, 1))
        self.assertEqual(r["labellers"][0]["hedged"], 1)


class CodebookTest(unittest.TestCase):
    def test_the_codebook_example_is_on_a_fact_no_hypothesis_tests(self):
        codebook = (TRACK / "docs" / "LABELLING.md").read_text()
        self.assertIn("National Day", codebook)
        banks = [json.dumps(h).lower() for h in load_hypotheses()]
        self.assertEqual([h for h in banks if "national day" in h or "1 august" in h], [])

    def test_the_page_and_the_codebook_give_the_same_rules(self):
        page = (TRACK / "web" / "review.html").read_text()
        for rule in ("Behaviour cases", "It hedges", "Judge by the reference only"):
            self.assertIn(rule, page)
        self.assertNotIn("the reference does not settle it", page)


class LanguageCheckTest(unittest.TestCase):
    """The native speakers' check reads the verified prompts of the recorded runs."""

    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        root = Path(d.name)
        use_runs(self, root / "runs", root / "data-runs")
        patch(self, mock.patch.object(review_set, "PROMPT_RUNS", ("r1", "r2", "not-here")),
              mock.patch.object(review, "RATINGS", root / "language.jsonl"))
        self.write(root / "data-runs" / "r1", [
            ("h1", "attacker", "S0", None),
            ("h1", "mutator", {"en": "E1", "gsw": "G-first-try"}, {"gsw": "German"}),
            ("h1", "attacker", "S1", None),
            ("h1", "mutator", {"en": "E1", "gsw": "G1"}, {"gsw": "Swiss German"}),
            ("h1", "verifier", None, None),
            ("h2", "mutator", {"en": "E2", "gsw": "G2"}, {"gsw": "German"})])  # never verified
        self.write(root / "data-runs" / "r2", [
            ("h1", "mutator", {"en": "E1", "gsw": "G1"}, {"gsw": "Swiss German"}),
            ("h1", "verifier", None, None),
            ("h3", "attacker", "S3", None),
            ("h3", "mutator", {"en": "E3", "gsw": "G3", "rm": "R3"}, {"gsw": "German"}),
            ("h3", "verifier", None, None)])

    @staticmethod
    def write(folder: Path, steps):
        def data(node, prompts, detected):
            if node == "attacker":
                return {"prompt": prompts}
            return {"prompts": prompts, "detected": detected} if prompts else {}
        events = [{"hypothesis": h, "node": node, "status": "done" if prompts else "start",
                   "data": data(node, prompts, detected)} for h, node, prompts, detected in steps]
        folder.mkdir(parents=True)
        (folder / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))

    def test_each_verified_prompt_once_with_the_attackers_prompt_it_was_translated_from(self):
        found = {s["question"]: s for s in review_set.stimuli("gsw")}
        self.assertEqual(set(found), {"G1", "G3"})
        self.assertEqual((found["G1"]["source"], found["G1"]["detected"]), ("S1", "Swiss German"))
        self.assertEqual([(s["question"], s["source"]) for s in review_set.stimuli("rm")],
                         [("R3", "S3")])
        self.assertEqual(review_set.stimuli("gsw"), review_set.stimuli("gsw"))
        shown = review.stimuli_session("gsw", "Ann")["items"]
        self.assertFalse(any("detected" in s for s in shown))
        with self.assertRaises(ValueError):
            review_set.stimuli("de")

    def test_ratings_are_counted_beside_the_harness_check_and_between_speakers(self):
        ids = {s["question"]: s["id"] for s in review_set.stimuli("gsw")}
        review.save_rating("Ann", ids["G1"], "natural")
        review.save_rating("Ann", ids["G3"], "not_this_language", "Standard German")
        review.save_rating("Ben", ids["G1"], "odd")
        review.save_rating("Ben", ids["G1"], "natural")
        for label in ("fine", ["natural"]):
            with self.assertRaises(ValueError):
                review.save_rating("Ann", ids["G1"], label)
        self.assertEqual(set(review._latest(review.RATINGS)[0]),
                         {"labeller", "id", "rating", "note", "at"})
        gsw = review.language_report()["gsw"]
        self.assertEqual(gsw["ratings"], {"natural": {"n": 2, "harness_names_it": 2},
                                          "odd": {"n": 0, "harness_names_it": 0},
                                          "not_this_language": {"n": 1, "harness_names_it": 0}})
        (pair,) = gsw["between_people"]
        self.assertEqual({k: pair[k] for k in ("labellers", "n", "agree", "raw_agreement")},
                         {"labellers": ["Ann", "Ben"], "n": 1, "agree": 1, "raw_agreement": 1.0})
        self.assertNotIn("kappa", pair)
        self.assertEqual(review.stimuli_session("gsw", "Ann")["done"][ids["G3"]],
                         {"label": "not_this_language", "note": "Standard German", "hedged": False})


if __name__ == "__main__":
    unittest.main()
