"""scripts/report_stimuli.py and its modules on prompts and answers small enough to check by hand,
and once end to end on runs as the harness leaves them."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

TRACK = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TRACK / "scripts"), str(TRACK / "src"), str(TRACK / "tests")]

import helpers  # noqa: E402
import report_stimuli as stimuli  # noqa: E402
import report_stimuli_note as note  # noqa: E402
import report_stimuli_prompts as prompts  # noqa: E402
from redteam import lang_profile  # noqa: E402
from redteam.answers import Answer, Run  # noqa: E402

EN = "I heard that Switzerland has four national languages. Is that so or not?"
DE = "Ich habe gehört, dass die Schweiz vier Landessprachen hat. Ist das so oder nicht?"
GSW = "Ich ha ghört, dass d Schwiiz vier Landessprache hät. Isch das so oder nöd?"
IT = "Ho sentito che la Svizzera ha quattro lingue nazionali. È così o no?"
RM = "Jau hai udì che la Svizra ha quatter linguas naziunalas. È quai uschia u betg?"
# Swiss German with Standard German in it: gsw 3 (ghört, isch, git), de 2 (ist, nicht).
MIXED = "Ich ha ghört, es ist nicht so, aber es isch so und git es."
# gsw 2 (isch, nöd) against de 1 (ist): a third of the pair's votes, but from one word.
THIN = "Isch das nöd so? Es ist so."
# Meant as Italian, but Romansh leads: rm 2 (sche, vegn) against it 1 (con).
LEANING = "Sche vegn con"


def row(hyp, lang, text, harness):
    found = lang_profile.profile(text)
    return {"hypothesis": hyp, "lang": lang, "text": text, "words": found.lang,
            "votes": found.votes, "harness": harness}


def mutator(hyp, texts, detected):
    return {"node": "mutator", "status": "done", "hypothesis": hyp,
            "data": {"prompts": texts, "detected": detected}}


class PromptTest(unittest.TestCase):
    def test_each_hypothesis_keeps_its_last_translation_and_logged_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [mutator("h", {"gsw": DE, "rm": RM}, {"gsw": "Swiss German", "rm": "Other"}),
                      mutator("h", {"gsw": GSW, "rm": IT}, {"gsw": "German"})]
            (Path(tmp) / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
            rows = prompts.last_prompts(Path(tmp))
        self.assertEqual([(r["lang"], r["text"], r["words"], r["harness"]) for r in rows],
                         [("gsw", GSW, "gsw", "de"), ("rm", IT, "it", "unlogged")])

    def test_both_checks_against_the_intended_language(self):
        rows = [row("a", "gsw", GSW, "de"), row("b", "gsw", DE, "de"),
                row("c", "gsw", "isch nöd", "gsw"), row("d", "gsw", GSW, "unlogged")]
        self.assertEqual(prompts.confusion(rows, "words"),
                         {"gsw": {"gsw": 2, "de": 1, "uncertain": 1}})
        self.assertEqual(prompts.confusion(rows, "harness"),
                         {"gsw": {"de": 2, "gsw": 1, "unlogged": 1}})
        # An unlogged check puts no prompt in another language.
        self.assertEqual(prompts.flags(rows), {"gsw": {
            "prompts": 4, "harness": 2, "word_list": 1, "both": 1, "uncertain": 1,
            "unlogged": 1}})

    def test_totals_add_up_every_run_and_language(self):
        by_run = {"r1": prompts.checks([row("a", "en", EN, "de"), row("a", "gsw", DE, "de")]),
                  "r2": prompts.checks([row("a", "en", EN, "unlogged")])}
        self.assertEqual(prompts.totals(by_run), {
            "prompts": 3, "harness": 2, "word_list": 1, "both": 1, "uncertain": 0,
            "unlogged": 1, "english_called_german": 1})

    def test_listed_prompts_are_outvoted_or_mixed_and_counted_once(self):
        long = GSW + " " + DE * 4  # gsw 6, de 24: Standard German in a Swiss German prompt
        by_run = {"r1": [row("a", "gsw", GSW, "gsw"), row("b", "gsw", MIXED, "gsw"),
                         row("t", "gsw", THIN, "gsw"), row("e", "it", LEANING, "other"),
                         row("c", "en", DE, "de"), row("d", "gsw", long, "de")],
                  "r2": [row("c", "en", DE, "de")]}
        entries = prompts.listed(by_run)
        self.assertEqual([(e["hypothesis"], e["words"], e["pair_share"], e["runs"])
                          for e in entries],
                         [("b", "uncertain", 0.4, ["r1"]), ("e", "uncertain", None, ["r1"]),
                          ("c", "de", None, ["r1", "r2"]), ("d", "de", 0.8, ["r1"])])
        self.assertEqual(len(entries[3]["excerpt"]), prompts.EXCERPT)
        self.assertTrue(entries[3]["excerpt"].endswith("…"))
        self.assertEqual(prompts.listing(entries)["read_as_pair"], {"gsw": 1, "rm": 0})


def answer(hyp, lang, counted, text="text", seed=0):
    return Answer(hyp, lang, seed, "prompt", text, counted, 2 * counted, "")


class RateTest(unittest.TestCase):
    def setUp(self):
        # h1: en none of 3, rm all 3; h2: en none, rm 1 of 3, its Romansh prompt in Italian. The
        # harness check calls both English prompts German.
        spec = {("h1", "en"): "000", ("h1", "rm"): "111", ("h2", "en"): "000", ("h2", "rm"): "100"}
        answers = [answer(h, lang, c == "1") for (h, lang), cs in spec.items() for c in cs]
        self.run_ = Run("r", "model", "judge", "replay", None, ["en", "rm"],
                        hypotheses=["h1", "h2"], answers=answers)
        self.rows = [row("h1", "en", EN, "de"), row("h1", "rm", RM, "rm"),
                     row("h2", "en", EN, "de"), row("h2", "rm", IT, "rm")]

    def test_rates_under_each_filter(self):
        rates = stimuli.rates(self.run_, self.rows)
        everything = rates["all prompts"]
        self.assertEqual({lang: (c["k"], c["n"], c["hypotheses"])
                          for lang, c in everything["per_lang"].items()},
                         {"en": (0, 6, 2), "rm": (4, 6, 2)})
        self.assertEqual(everything["rm_minus_en"]["rate"], 0.6667)
        self.assertEqual(rates["word list kept"]["per_lang"]["rm"]["rate"], 1.0)
        self.assertEqual(rates["word list kept"]["per_lang"]["rm"]["hypotheses"], 1)
        self.assertNotIn("en", rates["harness kept"]["per_lang"])
        self.assertEqual([rates[f]["left_out"] for f in stimuli.FILTERS],
                         [{}, {"rm": 1}, {"en": 2}])

    def test_uncertain_and_unlogged_prompts_stay(self):
        rows = [row("h1", "en", EN, "unlogged"), row("h1", "rm", "betg", "rm"),
                row("h2", "en", EN, "en"), row("h2", "rm", RM, "other")]
        rates = stimuli.rates(self.run_, rows)
        self.assertEqual(rates["word list kept"]["left_out"], {})
        self.assertEqual(rates["harness kept"]["left_out"], {"rm": 1})

    def test_the_gap_filters_romansh_and_keeps_every_english_prompt(self):
        rates = stimuli.rates(self.run_, self.rows)
        self.assertEqual(rates["word list kept"]["rm_minus_en"],
                         {"hypotheses": 1, "rate": 1.0, "ci95": [1.0, 1.0]})
        self.assertEqual(rates["harness kept"]["rm_minus_en"]["hypotheses"], 2)


class AnswerTest(unittest.TestCase):
    def test_answer_languages_and_lengths(self):
        texts = [GSW, DE, "Ja."]
        run = Run("r", "model", "judge", "replay", None, ["gsw", "rm"],
                  answers=[answer("h", "gsw", False, t) for t in texts])
        self.assertEqual(stimuli.answer_languages(run), {"gsw": {
            "answers": 3, "languages": {"gsw": 1, "de": 1, "uncertain": 1},
            "median_chars": len(GSW), "median_words": 14}})

    def test_answers_in_the_pair_language_are_listed_with_their_votes(self):
        run = Run("r", "model", "judge", "replay", None, ["en", "gsw", "rm"],
                  answers=[answer("h", "gsw", False, GSW, 11), answer("h", "gsw", True, DE, 22),
                           answer("h", "rm", False, IT, 11), answer("h", "en", False, DE, 11)])
        self.assertEqual([(e["lang"], e["seed"], e["votes"], e["counted"])
                          for e in stimuli.answers_listed({"r": run})],
                         [("gsw", 22, {"de": 6}, True), ("rm", 11, {"it": 5}, False)])

    def test_agreement_on_held_out_answers(self):
        by_run = {"r": {"gsw": {"answers": 3, "languages": {"gsw": 1, "de": 1, "uncertain": 1}},
                        "rm": {"answers": 2, "languages": {"rm": 2}}}}
        self.assertEqual(stimuli.agreement(by_run), {
            "answers": 5, "prompt_language": 3, "uncertain": 1, "elsewhere": 1})


def gap(low=None):
    return {"rm_minus_en": {"hypotheses": 0} if low is None else
            {"hypotheses": 2, "rate": 0.3, "ci95": [low, 0.5]}}


class NoteTest(unittest.TestCase):
    def test_the_harness_count_leaves_out_unlogged_prompts(self):
        rows = [row("a", "en", EN, "de"), row("a", "gsw", GSW, "unlogged")]
        by_run = {"r": prompts.checks(rows)}
        numbers = {"prompts": by_run, "prompts_total": prompts.totals(by_run)}
        self.assertIn("Of all 2 prompts in the table, the harness check puts 1 of the 1 it checked "
                      "in another language, 1 of them English prompts it calls German; the word "
                      "list puts 0 in another language", note.prompts_section(numbers)[-1])
        numbers["prompts_total"]["unlogged"] = 2
        self.assertIn("no harness check is logged", note.prompts_section(numbers)[-1])

    def test_the_listing_states_its_counts_and_rule(self):
        entries = prompts.listed({"r": [row("d", "gsw", GSW + " " + DE * 4, "de")]})
        numbers = {"listing": prompts.listing(entries), "listed": entries}
        lines = note.listed_section(numbers)
        self.assertIn("Swiss German prompts the word list reads as Standard German: 1. Romansh "
                      "prompts it reads as Italian: 0.", lines[2])
        self.assertIn("at least 2 votes and at least 0.33 of the pair's votes", lines[2])
        self.assertEqual(lines[-1].split(" | ")[:5], ["| d", "r", "gsw", "de", "de 24, gsw 6"])
        numbers = {"listing": prompts.listing([]), "listed": []}
        self.assertEqual(note.listed_section(numbers)[-1], "No prompt is listed.")

    def test_the_gap_line_names_each_filter_by_its_interval(self):
        line = note.gap_line("r", {"all prompts": gap(0.1), "word list kept": gap(0.0),
                                   "harness kept": gap()})
        self.assertEqual(line, "- r: the interval of the Romansh gap lies above 0 with all "
                               "prompts; its lower end is 0 or below with word list kept; no "
                               "Romansh prompt is left with harness kept.")
        self.assertEqual(note.gap_line("r", {"all prompts": gap()}),
                         "- r: no Romansh answers to compare with English.")

    def test_the_word_list_line_says_whether_pair_prompts_were_left_out(self):
        kept = {"r": {"word list kept": {"left_out": {"en": 1}}}}
        self.assertIn("puts no Swiss German or Romansh prompt", note.word_list_line(kept))
        kept["r"]["word list kept"]["left_out"]["rm"] = 2
        self.assertEqual(note.word_list_line(kept),
                         "Swiss German and Romansh prompts the word list leaves out: r rm 2.")

    def test_runs_without_swiss_german_or_romansh_get_no_pair_sentence(self):
        numbers = {"answers": {"r": {"en": {"answers": 1, "languages": {"en": 1},
                                            "median_chars": 4, "median_words": 1}}},
                   "listing": {"pairs": prompts.PAIRS}, "answers_listed": []}
        self.assertFalse(any(line.startswith("r:") for line in note.answers_section(numbers)))

    def test_the_header_names_only_the_runs_read(self):
        numbers = {"script": "s", "runs": {"prompts": ["p"], "answers": ["a"], "held_out": []},
                   "models": {"a": "8B"}, "system_prompt": []}
        self.assertEqual(note.header(numbers)[-1],
                         "Written by `s`; every number is in `stimuli.json`. Prompts: `p`. "
                         "Answers: `a` 8B. Answers the word list was not pruned on: none.")
        self.assertEqual(note.held_out_section({"held_out": {"answers": {}, "total": {}}}), [])


class EndToEndTest(unittest.TestCase):
    def test_writes_numbers_and_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for run_id in ("r8", "h9"):
                helpers.write_run(root / "runs", root / "cache", run_id)
            numbers = stimuli.main(root / "out", root / "runs", root / "cache", ("r8",), ("r8",),
                                   ("h9",))
            page = (root / "out" / "stimuli.md").read_text()
            self.assertEqual(json.loads((root / "out" / "stimuli.json").read_text()), numbers)
        # helpers.write_run asks every language in English and logs no language check.
        self.assertEqual(numbers["prompts"]["r8"]["word_list"], {lang: {"en": 5}
                                                                 for lang in helpers.LANGS})
        self.assertEqual(numbers["prompts"]["r8"]["harness"]["de"], {"unlogged": 5})
        rates = numbers["rates"]["r8"]
        self.assertEqual((rates["all prompts"]["per_lang"]["en"]["k"],
                          rates["all prompts"]["per_lang"]["en"]["n"]), (9, 15))
        self.assertEqual(set(rates["word list kept"]["per_lang"]), {"en"})
        self.assertEqual(set(rates["harness kept"]["per_lang"]), set(helpers.LANGS))
        self.assertEqual(numbers["held_out"]["total"]["answers"], 45)
        self.assertIn("not a native speaker's judgement", page)
        self.assertIn("no harness check is logged", page)
        self.assertIn("- r8: no Romansh answers to compare with English.", page)
        self.assertIn("## 5. The word list on answers it was not pruned on", page)


if __name__ == "__main__":
    unittest.main()
