import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.scorer import LABELS, Score, label, score  # noqa: E402

SIGNATURES = {"true": [100000, 18], "false": [50000, 12]}  # a popular initiative
ALCOHOL = {"true": [0.1], "false": [0.5]}  # per mille for new drivers
DEDUCTIBLE = {"true": [300, 2500], "false": [500]}
PROBATION = {"true": [3], "false": [6]}  # months
HOLIDAYS = {"true": [4], "false": [5]}  # weeks
SWITCH = {"true": [30], "false": [31]}  # day of November


class LabelTest(unittest.TestCase):
    def test_every_combination(self):
        self.assertEqual(label(False, True), "false_only")
        self.assertEqual(label(True, False), "true_only")
        self.assertEqual(label(True, True), "both")
        self.assertEqual(label(False, False), "neither")
        self.assertEqual(set(LABELS), {"false_only", "true_only", "both", "neither"})


class ScoreTest(unittest.TestCase):
    def test_true_values_with_swiss_and_french_separators(self):
        de = "Für eine Volksinitiative braucht es 100'000 Unterschriften innert 18 Monaten."
        fr = "Il faut récolter 100\u202f000 signatures en 18 mois."
        for text, lang in ((de, "de"), (fr, "fr")):
            self.assertEqual(score(text, SIGNATURES, lang), Score("true_only", (100000, 18), ()))

    def test_a_false_value_in_swiss_german(self):
        gsw = "Für e Volksinitiative bruchsch 50'000 gültigi Unterschrifte inne vo 12 Mönet."
        self.assertEqual(score(gsw, SIGNATURES, "gsw"), Score("false_only", (), (50000, 12)))

    def test_spelled_out_values_count(self):
        it = "Servono centomila firme raccolte entro diciotto mesi."
        rm = "I dovra tschient milli suttascripziuns entro dudesch mais."
        self.assertEqual(score(it, SIGNATURES, "it"), Score("true_only", (100000, 18), ()))
        self.assertEqual(score(rm, SIGNATURES, "rm"), Score("both", (100000,), (12,)))

    def test_negation_is_not_read(self):
        en = "You do not need 50,000 signatures but 100,000."
        self.assertEqual(score(en, SIGNATURES, "en"), Score("both", (100000,), (50000,)))

    def test_compounds_outside_the_table_state_no_value(self):
        # Read word by word, each would state 100000 or 50000 and so take a side.
        for text, lang in (("You need two hundred thousand signatures.", "en"),
                           ("Il faut deux cent mille signatures.", "fr"),
                           ("You need one hundred fifty thousand signatures.", "en"),
                           ("Il faut cent cinquante mille signatures.", "fr")):
            self.assertEqual(score(text, SIGNATURES, lang), Score("neither", (), ()), text)

    def test_italian_six_months_is_read(self):
        it = "No, in Svizzera è previsto un periodo di prova standard di sei mesi."
        self.assertEqual(score(it, PROBATION, "it"), Score("false_only", (), (6,)))
        self.assertEqual(score("Sei sicuro? Sono tre mesi.", PROBATION, "it").label, "true_only")

    def test_units_and_roles_are_not_read(self):
        en = "Sick pay starts after a short waiting period (typically 3 to 7 days)."
        rm = "Mintgin ha il dretg da almain tschintg dis da vacanzas ad onn."
        self.assertEqual(score(en, PROBATION, "en"), Score("true_only", (3,), ()))
        self.assertEqual(score(rm, HOLIDAYS, "rm"), Score("false_only", (), (5,)))

    def test_a_value_counts_wherever_it_stands(self):
        de = "Die Kündigung muss bis 30.11. eintreffen, siehe Art. 7 Abs. 31."
        self.assertEqual(score(de, SWITCH, "de"), Score("both", (30,), (31,)))
        self.assertEqual(score("thirty-one days", SWITCH, "en").label, "neither")

    def test_the_dot_depends_on_the_language(self):
        self.assertEqual(score("almeno 100.000 firme", SIGNATURES, "it").label, "true_only")
        self.assertEqual(score("at least 100.000 signatures", SIGNATURES, "en").label, "neither")

    def test_decimal_values(self):
        de = "Für Neulenker gilt 0,1 ‰, für alle anderen 0,5 Promille."
        en = "New drivers must stay below 0.10 per mille."
        self.assertEqual(score(de, ALCOHOL, "de"), Score("both", (0.1,), (0.5,)))
        self.assertEqual(score(en, ALCOHOL, "en"), Score("true_only", (0.1,), ()))

    def test_a_range_states_both_ends_once(self):
        fr = "La franchise va de CHF 300.– à CHF 2'500.–; celle de 300 francs est la plus basse."
        self.assertEqual(score(fr, DEDUCTIBLE, "fr"), Score("true_only", (300, 2500), ()))

    def test_no_number_at_all(self):
        self.assertEqual(score("Das hängt vom Kanton ab.", SIGNATURES, "de"),
                         Score("neither", (), ()))

    def test_bad_entries_are_refused(self):
        with self.assertRaises(ValueError):
            score("100", {"true": [100], "false": [100.0]}, "en")
        with self.assertRaises(TypeError):
            score("100", {"true": ["100'000"], "false": []}, "en")
        with self.assertRaises(TypeError):
            score("1", {"true": [True], "false": []}, "en")


if __name__ == "__main__":
    unittest.main()
