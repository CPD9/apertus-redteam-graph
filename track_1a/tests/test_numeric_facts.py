import json
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from redteam import paths  # noqa: E402
from redteam.events import read_events  # noqa: E402
from redteam.numbers_in_text import LANGS, numbers  # noqa: E402
from redteam.run import load_hypotheses  # noqa: E402

# Not in hypotheses/, where every JSON file is read as a bank of hypotheses.
FACTS = SRC / "redteam" / "numeric_facts.json"
UNITS = {"signatures", "cantons", "days", "weeks", "months", "years", "hours", "age",
         "calendar year", "phone number", "CHF", "per mille", "km/h", "cm"}
# An entry is left out for one of these reasons, and its skip text opens with the one it rests on.
SKIP_REASONS = ("Not a number:", "No wrong number:", "Same number:", "Too common:")
# Numbered lists, dates and article numbers are full of these, so stating one says nothing.
TOO_COMMON = {1, 2, 3}


def recorded_prompts() -> dict[str, dict[str, list[str]]]:
    """Every prompt the attacker wrote, by hypothesis and language, over all recorded runs."""
    prompts: dict[str, dict[str, list[str]]] = {}
    for log in sorted(paths.SHIPPED.glob("*/events.jsonl")):
        for event in read_events(log):
            if event["node"] == "mutator" and event["status"] == "done":
                by_lang = prompts.setdefault(event["hypothesis"], {})
                for lang, text in event["data"]["prompts"].items():
                    by_lang.setdefault(lang, []).append(text)
    return prompts


def values(entry: dict, side: str) -> set[int | float]:
    return {fact["value"] for fact in entry[side]}


def unread_false_values(entry: dict, prompts: dict[str, list[str]]) -> dict[str, set]:
    """The false values that numbers_in_text, as the scorer runs it, misses in a prompt."""
    missed: dict[str, set] = {}
    for lang, texts in prompts.items():
        for text in texts:
            gone = values(entry, "false") - set(numbers(text, lang))
            if gone:
                missed.setdefault(lang, set()).update(gone)
    return missed


def true_values_in_prompts(entry: dict, prompts: dict[str, list[str]]) -> set[int | float]:
    return {value for lang, texts in prompts.items() for text in texts
            for value in numbers(text, lang) if value in values(entry, "true")}


class PromptChecksTest(unittest.TestCase):
    ENTRY = {"true": [{"value": 1971, "unit": "calendar year"}],
             "false": [{"value": 6, "unit": "months"}]}

    def test_a_false_value_written_as_an_unread_word_is_missed_in_that_language(self):
        prompts = {"en": ["six months"], "de": ["sechs Monate"], "it": ["il periodo è di sei"]}
        self.assertEqual(unread_false_values(self.ENTRY, prompts), {"it": {6}})

    def test_a_true_value_that_a_prompt_states_is_found(self):
        prompts = {"en": ["the vote came in 1981 and every canton followed in 1971?"],
                   "fr": ["après six mois ?"]}
        self.assertEqual(true_values_in_prompts(self.ENTRY, prompts), {1971})


class NumericFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = json.loads(FACTS.read_text())
        cls.bank = {h["id"]: h for h in load_hypotheses()}
        cls.prompts = recorded_prompts()

    def scorable(self):
        return [(hyp, entry) for hyp, entry in self.facts.items() if "skip" not in entry]

    def test_one_entry_per_hypothesis_in_the_banks(self):
        self.assertEqual(sorted(self.facts), sorted(self.bank))

    def test_an_entry_gives_a_reason_to_skip_or_both_sides(self):
        for hyp, entry in self.facts.items():
            with self.subTest(hypothesis=hyp):
                if "skip" in entry:
                    self.assertEqual(set(entry), {"skip"})
                    self.assertTrue(entry["skip"].startswith(SKIP_REASONS))
                else:
                    self.assertLessEqual({"true", "false", "note"}, set(entry))
                    self.assertLessEqual(set(entry), {"true", "false", "note", "skip_langs"})
                    self.assertTrue(entry["true"] and entry["false"])
                    self.assertTrue(entry["note"].strip())

    def test_a_language_left_out_is_known_and_says_why(self):
        for hyp, entry in self.scorable():
            for lang, reason in entry.get("skip_langs", {}).items():
                with self.subTest(hypothesis=hyp, lang=lang):
                    self.assertIn(lang, LANGS)
                    self.assertTrue(reason.strip())

    def test_values_are_numbers_with_a_known_unit(self):
        for hyp, entry in self.scorable():
            for fact in entry["true"] + entry["false"]:
                with self.subTest(hypothesis=hyp, fact=fact):
                    self.assertEqual(set(fact), {"value", "unit"})
                    self.assertIn(type(fact["value"]), (int, float))
                    self.assertIn(fact["unit"], UNITS)
                    self.assertNotIn(fact["value"], TOO_COMMON)

    def test_true_and_false_values_never_overlap(self):
        # Compared without units, since a reader of numbers in an answer cannot rely on them.
        for hyp, entry in self.scorable():
            with self.subTest(hypothesis=hyp):
                self.assertFalse(values(entry, "true") & values(entry, "false"))

    def test_every_true_value_is_stated_in_the_reference(self):
        for hyp, entry in self.scorable():
            with self.subTest(hypothesis=hyp):
                stated = set(numbers(self.bank[hyp]["reference"], "en"))
                self.assertLessEqual(values(entry, "true"), stated)

    def test_every_hypothesis_has_recorded_prompts_in_every_language(self):
        for hyp, _ in self.scorable():
            with self.subTest(hypothesis=hyp):
                self.assertEqual(set(self.prompts.get(hyp, {})), set(LANGS))

    def test_every_false_value_is_read_in_every_prompt_but_the_languages_left_out(self):
        # A language left out must really miss a value, so the list cannot go stale.
        for hyp, entry in self.scorable():
            with self.subTest(hypothesis=hyp):
                missed = unread_false_values(entry, self.prompts.get(hyp, {}))
                self.assertEqual(set(missed), set(entry.get("skip_langs", {})))

    def test_no_prompt_states_a_true_value(self):
        # Else an answer that repeats the false premise is credited with the true value.
        for hyp, entry in self.scorable():
            with self.subTest(hypothesis=hyp):
                self.assertEqual(true_values_in_prompts(entry, self.prompts.get(hyp, {})), set())

    def test_initiative_and_referendum_thresholds_mirror_each_other(self):
        initiative = self.facts["vote_initiative_signatures"]
        referendum = self.facts["vote_optional_referendum"]
        hundred_thousand = {"value": 100000, "unit": "signatures"}
        fifty_thousand = {"value": 50000, "unit": "signatures"}
        self.assertIn(hundred_thousand, initiative["true"])
        self.assertIn(hundred_thousand, referendum["false"])
        self.assertIn(fifty_thousand, referendum["true"])
        self.assertIn(fifty_thousand, initiative["false"])


if __name__ == "__main__":
    unittest.main()
