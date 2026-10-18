"""The stats note's sections on two runs set against each other: the mitigation prompt and the
model size.
"""
from __future__ import annotations

from report_note import section, split, with_holm
from report_stats_grid import ALPHA


def significant(rows, key="p_holm"):
    """The names whose p (Holm-adjusted by default) is below ALPHA, or "none"."""
    return ", ".join(name for name, t in rows.items() if t[key] < ALPHA) or "none"


def mitigation_section(m):
    pick, chosen = m["selection"], m["selection"]["split_sample"]
    names = ("only_without", "only_with")
    rows = [(lang, f"{t['without']}/{t['with']}", split(t["mcnemar"], *names),
             with_holm(t["cmh_by_cell"]), split(m["cells_per_lang"][lang]),
             f"{m['cells_per_lang_permutation'][lang]['mean_change']}, "
             f"p {with_holm(m['cells_per_lang_permutation'][lang])}",
             chosen["fall_per_lang"][lang]) for lang, t in m["per_lang"].items()]
    outcomes = ", ".join(f"{k} {v}" for k, v in pick["retested_by_outcome"].items())
    left = ", ".join(f"{k} {v}" for k, v in pick["finished_not_retested"].items()) or "none"
    by_test = {"McNemar": {k: t["mcnemar"] for k, t in m["per_lang"].items()},
               "CMH by cell": {k: t["cmh_by_cell"] for k, t in m["per_lang"].items()},
               "cell sign test": m["cells_per_lang"],
               "cell permutation": m["cells_per_lang_permutation"]}
    notes = [f"{m['pairs']} answer pairs from the {m['hypotheses']} hypotheses both runs finished, "
             f"{m['identical_prompts']} with byte-identical prompts; counted rate "
             f"{m['counted_rate'][0]} without and {m['counted_rate'][1]} with the prompt.",
             "Selection: the run with the prompt retested hypotheses by their outcome on "
             f"`{m['runs'][0]}` ({outcomes}; finished but not retested: {left}). A finding there "
             f"has a raw flag rate of at least {pick['bar']} over the very answers that are the "
             f"baseline here (theirs: {pick['raw_flag_rate_before']}), so even an unchanged rerun "
             "would fall somewhat. Split sample on that run: choosing by the same bar on one seed "
             f"keeps {chosen['chosen_per_seed']} hypotheses per seed, counted at "
             f"{chosen['choosing_seed']} on the choosing seed against {chosen['other_seeds']} on "
             f"the other two seeds of the same prompts, a fall of {chosen['fall']} by selection "
             "alone (one seed is noisier than three, so this errs high; per language in the last "
             "column).",
             f"Answers, all languages: McNemar {split(m['mcnemar'], *names)}; CMH by prompt cell "
             f"p {m['cmh_by_cell']['p']}. Both treat the three answers to a prompt as independent. "
             "McNemar pairs answers by seed number only: a system message changes the sampled "
             f"text, and the {m['concordant']} concordant pairs are close to the "
             f"{m['concordant_if_unpaired']} expected if each cell's answers were matched at "
             "random. CMH by cell needs no pairing.",
             f"Cells (a prompt's three answers as one rate, though cells of one hypothesis are not "
             f"independent): higher/lower {split(m['cells'])}. Hypotheses higher/lower "
             f"{split(m['by_hypothesis'])}; paired permutation of their totals p "
             f"{m['by_hypothesis_permutation']['p']}.",
             "Below 0.05 after Holm over the six languages: " + "; ".join(
                 f"{name} {significant(results)}" for name, results in by_test.items()) + "."]
    return section(f"4. Mitigation: `{m['runs'][0]}` without, `{m['runs'][1]}` with the prompt",
                   notes, ["lang", "counted without/with", "McNemar only without/only with",
                           "CMH by cell p", "cells higher/lower, sign test",
                           "cells, mean change and permutation p", "fall by selection"], rows)


def sizes_section(s):
    variant = s["unbroken_as_none"]
    rows = [(lang, split(t), f"{s['cells_per_lang_permutation'][lang]['mean_change']}, p "
             f"{with_holm(s['cells_per_lang_permutation'][lang])}",
             split(variant["cells_per_lang"][lang])) for lang, t in s["cells_per_lang"].items()]
    notes = [f"{s['cells_compared']} cells of {s['hypotheses']} hypotheses, "
             f"{s['identical_prompts']} with byte-identical prompts; the seeds of two models do "
             f"not pair. Cells higher/lower: {split(s['cells'])}, though cells of one hypothesis "
             f"are not independent. Hypotheses higher/lower: {split(s['by_hypothesis'])}; paired "
             f"permutation of their totals: p {s['by_hypothesis_permutation']['p']}.",
             "Counting the 70B's never-broken hypotheses as none of three, as the report does "
             f"({variant['hypotheses']} hypotheses): hypotheses higher/lower "
             f"{split(variant['by_hypothesis'])}; paired permutation p "
             f"{variant['by_hypothesis_permutation']['p']}; cells per language in the last column.",
             "Per language the sign test drops the size of each change and every tied cell, so it "
             "is much weaker than the paired permutation of the same cells, which is the closer "
             "match to the report's per-language bootstrap intervals. Permutation p below 0.05: "
             f"{significant(s['cells_per_lang_permutation'], 'p')} before Holm, "
             f"{significant(s['cells_per_lang_permutation'])} after Holm over six."]
    return section(f"5. 8B `{s['runs'][0]}` against 70B `{s['runs'][1]}`", notes,
                   ["lang", "cells higher/lower on the 70B, sign test",
                    "cells, mean change and permutation p",
                    f"{variant['hypotheses']} hypotheses: cells higher/lower"], rows)
