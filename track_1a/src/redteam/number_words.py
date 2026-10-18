"""The words numbers_in_text reads as numbers, per language: number words, the units that are not
numbers, the parts that only close a compound, and the words that count only before a unit of time.
"""

UNITS = ("per cent", "pour cent", "per cento", "per tschient",
         "per mille", "pour mille", "pro mille", "per milli")

# Alternative spellings are split by "|"; a space or hyphen in a spelling matches either.
WORDS = [  # value, en, de, gsw (on top of de), fr, it, rm
    (2, "two", "zwei", "zwöi|zwee|zwo|zwoi", "deux", "due", "dus|duas"),
    (3, "three", "drei", "drü", "trois", "tre", "trais"),
    (4, "four", "vier", "", "quatre", "quattro", "quatter"),
    (5, "five", "fünf", "füf|föif|fümf", "cinq", "cinque", "tschintg"),
    (6, "six", "sechs", "sächs", "six", "sei", "sis"),
    (7, "seven", "sieben", "sibe|siebe", "sept", "sette", "set"),
    (8, "eight", "acht", "", "huit", "otto", "otg"),
    (9, "nine", "neun", "nüün|nün", "neuf", "nove", "nov"),
    (10, "ten", "zehn", "zäh|zää", "dix", "dieci", "diesch"),
    (11, "eleven", "elf", "ölf", "onze", "undici", "indesch"),
    (12, "twelve", "zwölf", "zwöif", "douze", "dodici", "dudesch"),
    (13, "thirteen", "dreizehn", "drizäh|dreizäh", "treize", "tredici", "tredesch"),
    (14, "fourteen", "vierzehn", "vierzäh", "quatorze", "quattordici", "quattordesch"),
    (15, "fifteen", "fünfzehn", "füfzäh|füffzäh", "quinze", "quindici", "quindesch"),
    (16, "sixteen", "sechzehn", "sächzäh|sechzäh", "seize", "sedici", "sedesch"),
    (17, "seventeen", "siebzehn", "sibezäh|sibzäh", "dix-sept", "diciassette", "deschset"),
    (18, "eighteen", "achtzehn", "achtzäh|achtzää", "dix-huit", "diciotto", "deschdotg"),
    (19, "nineteen", "neunzehn", "nüünzäh|nünzäh", "dix-neuf", "diciannove", "deschnov"),
    (20, "twenty", "zwanzig", "zwänzg|zwanzg", "vingt|vingts", "venti", "ventg"),
    (30, "thirty", "dreissig|dreißig", "drissg|drissig", "trente", "trenta", "trenta"),
    (40, "forty", "vierzig", "vierzg", "quarante", "quaranta", "quaranta"),
    (50, "fifty", "fünfzig", "füfzg|fufzg", "cinquante", "cinquanta", "tschuncanta"),
    (60, "sixty", "sechzig", "sächzg|sechzg", "soixante", "sessanta", "sessanta"),
    (64, "sixty-four", "vierundsechzig", "vierasächzg|vieresächzg", "soixante-quatre",
     "sessantaquattro", "sessantaquatter"),
    (65, "sixty-five", "fünfundsechzig", "füfasächzg|füfesächzg", "soixante-cinq",
     "sessantacinque", "sessantatschintg"),
    (100, "hundred|one hundred", "hundert|einhundert", "", "cent|cents", "cento", "tschient"),
    (1000, "thousand|one thousand", "tausend|eintausend", "tuusig|tausig", "mille", "mille",
     "milli"),
    (50_000, "fifty thousand", "fünfzigtausend", "füfzgtuusig|füfzgtausig", "cinquante mille",
     "cinquantamila", "tschuncanta milli"),
    (100_000, "hundred thousand|one hundred thousand",
     "hunderttausend|hundertausend|einhunderttausend", "hunderttuusig|hunderttausig",
     "cent mille", "centomila|cento mila", "tschient milli|tschientmilli"),
]
# No value of their own; read only so that they close a compound: "thirty-one", "trente et un".
PARTS = {"en": "one|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth",
         "fr": "et un|et une|et unième|deuxième|troisième|quatrième|cinquième|sixième"
               "|septième|huitième|neuvième"}
# "sei" is also "you are", "neuf" and "nov" also "new"; a plural unit of time tells them apart.
BEFORE_TIME = {"it": ("sei", "mesi|anni|settimane|giorni|ore"),
               "fr": ("neuf", "mois|ans|années|semaines|jours|heures"),
               "rm": ("nov", "mais|onns|emnas|dis|uras")}
