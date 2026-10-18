"""redteam.lang_profile on sentences whose language is not in doubt, and the marker lists it
reads."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam import lang_profile as lp  # noqa: E402

# One question in the six languages, so only the language changes between them.
SAME_QUESTION = {
    "en": "I heard that Switzerland has four national languages. Is that so or not?",
    "de": "Ich habe gehört, dass die Schweiz vier Landessprachen hat. Ist das so oder nicht?",
    "gsw": "Ich ha ghört, dass d Schwiiz vier Landessprache hät. Isch das so oder nöd?",
    "fr": "J'ai entendu dire que la Suisse a quatre langues nationales. Est-ce vrai ou pas ?",
    "it": "Ho sentito che la Svizzera ha quattro lingue nazionali. È così o no?",
    "rm": "Jau hai udì che la Svizra ha quatter linguas naziunalas. È quai uschia u betg?",
}


class SentenceTest(unittest.TestCase):
    def test_each_language_is_read_as_itself(self):
        for lang, text in SAME_QUESTION.items():
            with self.subTest(lang):
                found = lp.profile(text)
                self.assertEqual((found.lang, found.margin), (lang, 1.0))

    def test_swiss_german_against_standard_german(self):
        self.assertEqual(lp.profile("Isch das würkli so? Ich ha das nöd gwüsst, es isch scho "
                                    "chli komisch, öppis so z säge.").lang, "gsw")
        self.assertEqual(lp.profile("Ist das wirklich so? Ich habe es nicht gewusst, es ist "
                                    "schon etwas seltsam.").lang, "de")

    def test_romansh_against_italian(self):
        self.assertEqual(lp.profile("Quai n'è betg vair: il chantun ha ina lescha "
                                    "nova.").lang, "rm")
        self.assertEqual(lp.profile("Questo non è vero: il cantone ha una legge nuova.").lang,
                         "it")

    def test_the_words_that_voted_are_kept_in_order(self):
        self.assertEqual(lp.profile(SAME_QUESTION["gsw"]).matched,
                         [("ghört", "gsw"), ("d", "gsw"), ("schwiiz", "gsw"), ("hät", "gsw"),
                          ("isch", "gsw"), ("nöd", "gsw")])

    def test_a_word_two_languages_write_votes_for_neither(self):
        # Each text uses a word that another language writes too; it must not vote for that one.
        shared = {"Sche ti has dubis, dumonda": "en",  # Romansh ti has, 'you have'
                  "Ich han das so vereinbart": "rm",  # Swiss German han, 'have'
                  "kürzer as dr Probezeit": "en",  # Swiss German as, 'than'
                  "Nus ans legrain": "fr",  # Romansh ans, 'us'
                  "the Gender Equality Act (GEA)": "rm",  # Romansh gea, 'yes'
                  "Ich ha das einfach gmacht": "de"}  # written Swiss German einfach
        for text, lang in shared.items():
            with self.subTest(text):
                self.assertNotIn(lang, lp.profile(text).votes)


class EvidenceTest(unittest.TestCase):
    def test_no_marker_is_uncertain_without_a_best_language(self):
        self.assertEqual(lp.profile("Stimmt das? 1291!"), lp.Profile(lp.UNCERTAIN, "", 0.0, {}, []))

    def test_too_few_votes_are_uncertain_but_name_the_leader(self):
        found = lp.profile("isch nöd")
        self.assertEqual((found.lang, found.best, found.votes), (lp.UNCERTAIN, "gsw", {"gsw": 2}))

    def test_a_lead_of_one_vote_is_uncertain(self):
        # A Swiss German sentence quoting a German line: de 2 (ist, ein) against gsw 1 (isch).
        found = lp.profile('Er seit: "Die Welt ist ein Irrenhaus." Isch so.')
        self.assertEqual(found.votes, {"de": 2, "gsw": 1})
        self.assertEqual((found.lang, found.best), (lp.UNCERTAIN, "de"))

    def test_a_lead_of_two_votes_decides(self):
        found = lp.profile("isch nöd gsi, ist")
        self.assertEqual((found.lang, found.votes, found.margin), ("gsw", {"gsw": 3, "de": 1}, 0.5))

    def test_a_narrow_lead_is_uncertain(self):
        # de 4 (ist, nicht, auch, kann) against gsw 3 (isch, nöd, cha): margin 1/7.
        found = lp.profile("Es ist nicht so, und auch kann man. Es isch nöd so, me cha.")
        self.assertEqual(found.votes, {"de": 4, "gsw": 3})
        self.assertEqual((found.lang, found.best, found.margin), (lp.UNCERTAIN, "de", 0.1429))

    def test_a_tie_is_uncertain(self):
        found = lp.profile("ist nicht kann isch nöd cha")
        self.assertEqual((found.lang, found.margin), (lp.UNCERTAIN, 0.0))


class WordsTest(unittest.TestCase):
    def test_case_and_apostrophes_are_normalised(self):
        self.assertEqual(lp.words("Stimmt’s, dass D’Schwiiz z‘Züri"),
                         ["stimmt", "dass", "d'", "schwiiz", "z'", "züri"])
        self.assertEqual(lp.profile("ISCH NÖD GSI").lang, "gsw")

    def test_english_clitics_are_not_swiss_german_articles(self):
        self.assertEqual(lp.words("it's what I'd say, I'm sure"),
                         ["it", "what", "i", "say", "i", "sure"])
        self.assertNotIn("gsw", lp.profile("It's what I'd say, that's true.").votes)

    def test_an_elision_before_a_one_letter_word_keeps_both(self):
        self.assertEqual(lp.words("jusqu'à demain"), ["jusqu'", "à", "demain"])
        self.assertEqual(lp.matches("Èsi vair ch'i dat?"),
                         [("èsi", "rm"), ("vair", "rm"), ("ch'", "rm")])

    def test_the_letters_of_an_abbreviation_are_no_words(self):
        self.assertEqual(lp.words("U.S. law, d. h. z.B. D.Lgs. 196"), ["law"])
        self.assertEqual(lp.words("the U.S. law."), ["the", "law"])
        self.assertEqual(lp.profile("In the U.S. it is not the law.").votes, {"en": 5})

    def test_letters_after_digits_are_no_word(self):
        self.assertEqual(lp.words("the 1990s and 18avel"), ["the", "and"])

    def test_elided_markers_count_before_a_word(self):
        self.assertEqual(lp.matches("qu'il dell'esame ch'ins z'Züri"),
                         [("qu'", "fr"), ("dell'", "it"), ("ch'", "rm"), ("z'", "gsw")])


class MarkersTest(unittest.TestCase):
    def test_every_marker_is_written_as_words_reads_it(self):
        for word, lang in lp.markers().items():
            with self.subTest(word=word):
                text = word + "ab" if word.endswith("'") else word  # an elision needs a next word
                self.assertEqual(lp.words(text)[0], word)

    def test_every_language_explains_its_list(self):
        entries = json.loads(lp.MARKERS.read_text())
        self.assertEqual(list(entries), ["en", "de", "gsw", "fr", "it", "rm"])
        for lang, entry in entries.items():
            self.assertGreater(len(" ".join(entry["note"])), 200, lang)
            self.assertEqual(len(entry["markers"]), len(set(entry["markers"])), lang)

    def test_a_word_in_two_lists_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "markers.json"
            path.write_text(json.dumps({"de": {"note": [], "markers": ["isch"]},
                                        "gsw": {"note": [], "markers": ["isch"]}}))
            with mock.patch.object(lp, "MARKERS", path):
                lp.markers.cache_clear()
                self.addCleanup(lp.markers.cache_clear)
                with self.assertRaisesRegex(ValueError, "'isch' is a marker of both de and gsw"):
                    lp.markers()


if __name__ == "__main__":
    unittest.main()
