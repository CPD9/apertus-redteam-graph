import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from redteam.numbers_in_text import LANGS, numbers, phrase_key, spellings  # noqa: E402

NBSP, NARROW, THIN = "\u00a0", "\u202f", "\u2009"
HYPHEN, NO_BREAK_HYPHEN = "\u2010", "\u2011"


class ThousandsTest(unittest.TestCase):
    def test_apostrophes_group_thousands_in_every_language(self):
        for lang in LANGS:
            self.assertEqual(numbers("100'000 und 100’000", lang), [100000, 100000])

    def test_spaces_of_any_width_group_thousands(self):
        text = f"100 000, 50{NBSP}000, 2{NARROW}500 et 1{THIN}000{THIN}000"
        self.assertEqual(numbers(text, "fr"), [100000, 50000, 2500, 1000000])

    def test_a_dot_before_three_digits_groups_thousands_outside_english(self):
        self.assertEqual(numbers("almeno 100.000 firme", "it"), [100000])
        self.assertEqual(numbers("mindestens 100.000 Unterschriften", "de"), [100000])
        self.assertEqual(numbers("at least 100.000 signatures", "en"), [100])

    def test_a_comma_before_three_digits_groups_thousands_only_in_english(self):
        self.assertEqual(numbers("You need 100,000 signatures.", "en"), [100000])
        self.assertEqual(numbers("100,000", "de"), [100])

    def test_a_repeated_dot_or_comma_groups_thousands_in_any_language(self):
        self.assertEqual(numbers("1.000.000", "en"), [1000000])
        self.assertEqual(numbers("1,000,000", "fr"), [1000000])

    def test_grouping_and_decimal_marks_combine(self):
        self.assertEqual(numbers("CHF 1.000,50", "de"), [1000.5])
        self.assertEqual(numbers("CHF 1,000.50", "en"), [1000.5])
        self.assertEqual(numbers("CHF 1'000.50", "de"), [1000.5])
        self.assertEqual(numbers("1 000,50 francs", "fr"), [1000.5])

    def test_a_long_or_zero_led_head_does_not_group(self):
        self.assertEqual(numbers("bis Ende 2023 64 Jahre, 2023 500 Personen", "de"),
                         [2023, 64, 2023, 500])
        self.assertEqual(numbers("0.100", "de"), [0.1])

    def test_a_bare_list_of_three_digit_numbers_reads_as_one_number(self):
        # The known blind spot of space grouping: without commas, nothing tells the two apart.
        self.assertEqual(numbers("117 118 144", "de"), [117118144])

    def test_a_word_for_thousand_after_digits_multiplies_them(self):
        self.assertEqual(numbers("Servono 100mila firme in 18 mesi", "it"), [100000, 18])
        self.assertEqual(numbers("100 mila firme", "it"), [100000])
        self.assertEqual(numbers("100 thousand signatures", "en"), [100000])
        self.assertEqual(numbers(f"50{NBSP}Tausend", "de"), [50000])
        self.assertEqual(numbers("1,1 mila", "it"), [1100])
        self.assertEqual(numbers("1,25 mila", "it"), [1250])


class DecimalTest(unittest.TestCase):
    def test_comma_and_dot_decimals(self):
        self.assertEqual(numbers("0,1 und 0.1", "de"), [0.1, 0.1])
        self.assertEqual(numbers("3.5 tons, 6,8 %", "en"), [3.5, 6.8])

    def test_per_mille_and_per_cent(self):
        self.assertEqual(numbers("0,1 ‰ statt 0,5 Promille", "de"), [0.1, 0.5])
        self.assertEqual(numbers("0,5 per mille, il 10 per cento", "it"), [0.5, 10])
        self.assertEqual(numbers("50 pour cent", "fr"), [50])
        self.assertEqual(numbers("cinquante pour cent", "fr"), [50])

    def test_trailing_zeros_give_whole_numbers(self):
        self.assertEqual(numbers("CHF 300.00 and 0.10", "en"), [300, 0.1])
        self.assertIsInstance(numbers("300.00", "en")[0], int)

    def test_a_second_dot_makes_a_date(self):
        self.assertEqual(numbers("gültig bis 28.02.2025", "de"), [28, 2, 2025])
        self.assertEqual(numbers("seit dem 1.1.2024", "de"), [1, 1, 2024])
        self.assertEqual(numbers("SR 161.1, um 13.30 Uhr", "gsw"), [161.1, 13.3])

    def test_a_day_and_month_closed_by_a_dot_are_a_date_outside_english(self):
        self.assertEqual(numbers("Kündigung bis 30.11.", "de"), [30, 11])
        self.assertEqual(numbers("per 31.12. wächsle", "gsw"), [31, 12])
        self.assertEqual(numbers("The limit rose to 3.5.", "en"), [3.5])
        self.assertEqual(numbers("Die Grenze liegt bei 0.5.", "de"), [0.5])  # no day 0
        self.assertEqual(numbers("Die Grenze liegt bei 0,5.", "de"), [0.5])

    def test_known_misread_a_price_closing_a_sentence(self):
        self.assertEqual(numbers("Das Ticket kostet CHF 3.10.", "de"), [3, 10])


class CurrencyDateAndRangeTest(unittest.TestCase):
    def test_currency_marks_are_dropped(self):
        text = "CHF 300, Fr. 300.–, 300.- Fr., 300 Franken, CHF 1'000.–"
        self.assertEqual(numbers(text, "de"), [300, 300, 300, 300, 1000])
        self.assertEqual(numbers(f"zwischen CHF{NARROW}300 und CHF{NARROW}2{NARROW}500", "de"),
                         [300, 2500])

    def test_ordinals_and_dates(self):
        self.assertEqual(numbers("am 1. Januar 2000", "de"), [1, 2000])
        self.assertEqual(numbers("the 18th year, le 1er janvier", "en"), [18, 1])

    def test_ranges_give_both_ends(self):
        self.assertEqual(numbers("300–2500", "de"), [300, 2500])
        self.assertEqual(numbers("women born 1961-1969", "en"), [1961, 1969])
        self.assertEqual(numbers("CHF 0.20–0.70", "en"), [0.2, 0.7])

    def test_phone_numbers_keep_their_groups_apart(self):
        self.assertEqual(numbers("Tox Info Suisse 145, +41 44 251 51 51", "en"),
                         [145, 41, 44, 251, 51, 51])
        self.assertEqual(numbers("0848 134 134 oder 1414", "de"), [848, 134, 134, 1414])


class WordsTest(unittest.TestCase):
    def test_one_hundred_thousand_in_each_language(self):
        cases = {"en": "a hundred thousand signatures", "de": "hunderttausend Unterschriften",
                 "gsw": "hunderttuusig Unterschrifte", "fr": "cent mille signatures",
                 "it": "centomila firme", "rm": "tschient milli suttascripziuns"}
        for lang, text in cases.items():
            self.assertEqual(numbers(text, lang), [100000], lang)

    def test_eighteen_in_each_language(self):
        cases = {"en": "eighteen", "de": "achtzehn", "gsw": "achtzäh", "fr": "dix-huit",
                 "it": "diciotto", "rm": "deschdotg"}
        for lang, text in cases.items():
            self.assertEqual(numbers(f"{text} Monate", lang), [18], lang)

    def test_spellings_and_case(self):
        self.assertEqual(numbers("Hundertausend", "de"), [100000])
        self.assertEqual(numbers("Dix huit mois", "fr"), [18])
        self.assertEqual(numbers("dreissig oder dreißig", "de"), [30, 30])
        self.assertEqual(numbers("zwölf Mönet", "gsw"), [12])
        self.assertEqual(numbers("fümf Wuche Ferie, zwo Wuche", "gsw"), [5, 2])

    def test_every_hyphen_joins_a_spelling(self):
        self.assertEqual(numbers(f"dix{NO_BREAK_HYPHEN}huit mois", "fr"), [18])
        self.assertEqual(numbers(f"dix{HYPHEN}huit mois", "fr"), [18])
        self.assertEqual(numbers(f"sixty{NO_BREAK_HYPHEN}four", "en"), [64])

    def test_case_folds_outside_the_table_are_dropped(self):
        self.assertEqual(numbers("S\u0130X", "en"), [])  # dotted capital I folds to two letters
        self.assertEqual(numbers("\u017fix", "en"), [6])  # the long s folds to s

    def test_words_inside_longer_words_are_not_numbers(self):
        self.assertEqual(numbers("im 15. Jahrhundert, Hunderttausende", "de"), [15])
        self.assertEqual(numbers("la famille, recent", "fr"), [])
        self.assertEqual(numbers("il 18avel tschientaner", "rm"), [18])

    def test_a_word_joined_to_a_noun_still_counts(self):
        self.assertEqual(numbers("a three-month wait, the first two years", "en"), [3, 2])

    def test_compounds_outside_the_table_state_nothing(self):
        for text, lang in (("two hundred days", "en"), ("two hundred thousand", "en"),
                           ("one hundred fifty thousand", "en"),
                           ("one hundred and fifty thousand", "en"),
                           ("twenty-one thousand", "en"), ("2 hundred thousand", "en"),
                           ("deux cent mille", "fr"), ("cent cinquante mille", "fr"),
                           ("deux cents francs", "fr"), ("dus tschient milli", "rm")):
            self.assertEqual(numbers(text, lang), [], text)

    def test_tens_with_a_unit_or_an_ordinal_state_nothing(self):
        for text, lang in (("thirty-one days", "en"), ("the thirty-first", "en"),
                           ("trente et un jours", "fr"), ("le trente et unième", "fr"),
                           ("dix-huitième", "fr")):
            self.assertEqual(numbers(text, lang), [], text)

    def test_one_and_its_translations_are_not_numbers(self):
        for text, lang in (("one must sign", "en"), ("ein Jahr", "de"), ("un an", "fr"),
                           ("uno solo", "it")):
            self.assertEqual(numbers(text, lang), [], text)

    def test_ambiguous_words_count_only_before_a_unit_of_time(self):
        self.assertEqual(numbers("un periodo di prova di sei mesi", "it"), [6])
        self.assertEqual(numbers("tu sei d'accordo, sei il primo", "it"), [])
        self.assertEqual(numbers("neuf mois, dix-neuf mois", "fr"), [9, 19])
        self.assertEqual(numbers("un contrat neuf", "fr"), [])
        self.assertEqual(numbers("nov mais", "rm"), [9])
        self.assertEqual(numbers("in nov contract, il nov onn", "rm"), [])

    def test_known_misreads(self):
        self.assertEqual(numbers("a few thousand", "en"), [1000])
        self.assertEqual(numbers("außer Acht lassen", "de"), [8])

    def test_words_are_read_in_the_question_language_only(self):
        self.assertEqual(numbers("zwölf Jahre, dodici anni", "rm"), [])
        self.assertEqual(numbers("set the rules", "rm"), [7])

    def test_words_and_digits_come_in_reading_order(self):
        self.assertEqual(numbers("50 000 signatures en cent jours", "fr"), [50000, 100])
        self.assertEqual(numbers("Ende 2023 drei Kantone", "de"), [2023, 3])

    def test_no_spelling_has_two_values_in_one_language(self):
        for lang in LANGS:
            values = {}
            for spelling, value in spellings(lang):
                values.setdefault(phrase_key(spelling), set()).add(value)
            self.assertEqual({k: v for k, v in values.items() if len(v) > 1}, {}, lang)


if __name__ == "__main__":
    unittest.main()
