"""Each interval or test the report states: words that find it, then a reading written by hand of
how it is computed, what it rests on, and whether it treats answers (or clips) as independent.
Only the line numbers are computed, so a changed report can leave a reading stale.
"""
from __future__ import annotations

import re

CLAIMS = [
    (["difference −14 points, 95% CI −23 to −5", "(−7 points, 95% CI −20 to +7)"],
     "bootstrap of the pooled difference over hypotheses", "hypotheses as clusters", False),
    (["significant only in English, Swiss"], "six per-language bootstrap intervals read as tests, "
     "with no multiplicity adjustment (item 5 gives the cell permutation, Holm over six)",
     "hypotheses as clusters", False),
    (["Wrong answers (95% CI)", "74% (52–92)", "83% (50–100)", "71% (38–96)", "64% (28–89)",
      "never narrower than Wilson"], "bootstrap over variations x languages; 1 and 2 variations "
     "in findings 2 and 4", "variations and languages as clusters, floored at Wilson", False),
    (["48% (95% CI 36–60)", "48% (36–60)", "against 1% (0–3)"],
     "bootstrap over 8 dialects (one speaker each) x 60 sentences",
     "dialects and sentences as clusters", False),
    (["**Figure 1.**", "**Figure 4.**"], "pooled rate per language, bootstrap over hypotheses",
     "hypotheses as clusters", False),
    (["**Figure 2.**"], "Wilson interval of each hypothesis's 18 answers (6 prompts x 3 seeds)",
     "independent answers, though three share each prompt, so it is too narrow", True),
    (["**Figure 3.**"], "Wilson interval of each dialect's 60 clips of 60 distinct sentences",
     "independent clips, fair for distinct sentences; one speaker per dialect, so it covers that "
     "speaker, not the dialect", True),
    (["Cohen's κ, agreement beyond", "κ 0.14"], "point estimates, no interval", "none stated",
     False),
    (["from 29% to 12% (Romansh 52% to 14%)"], "rates, no interval or test in the text",
     "none stated", False),
]
INTERVAL = re.compile(r"95% CI|\(\d+–\d+\)|significan|κ")


def claims(report):
    """CLAIMS with the report lines that state each, and the lines that look like an interval or
    a test but match none of them."""
    lines = report.splitlines()
    found = [{"lines": [i + 1 for i, line in enumerate(lines) if any(w in line for w in words)],
              "states": words, "reading": {"method": method, "rests_on": rests_on,
                                           "assumes_independence": independent}}
             for words, method, rests_on, independent in CLAIMS]
    seen = {n for claim in found for n in claim["lines"]}
    return {"claims": found, "unlisted_lines": [i + 1 for i, line in enumerate(lines)
                                                if INTERVAL.search(line) and i + 1 not in seen]}
