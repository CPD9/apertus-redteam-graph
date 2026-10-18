"""The stats note (docs/audit/stats.md) from the numbers in stats.json."""
from __future__ import annotations

from report_note import grid_table, section, split, with_holm
from report_stats_note_runs import mitigation_section, sizes_section


def preamble(n):
    models = "; ".join(f"`{r}` {model}" for r, model in n["models"].items())
    covered = []
    for r, x in n["runs"].items():
        left = ", ".join(f"{h} ({o})" for h, o in x["coverage"]["left_out"].items())
        covered.append(f"`{r}` {x['coverage']['hypotheses']}" + (f", left out: {left}" if left
                                                                  else ""))
    return ["# Statistics audit", "",
            f"Written by `{n['script']}`; every number is in `stats.json`. Runs: {models}. Every "
            "test here was chosen after the runs were read, so all are post hoc.", "",
            "An answer counts by Answer.confirmed, which is the judge's verdict. The language "
            "effects (items 1, 2, 3 and 6) assume the judge scores every language alike; a "
            "difference between languages can come from the judge as well as from the model, and "
            "item 6 names a case against that assumption.", "",
            f"Hypotheses with verified answers: {'; '.join(covered)}. The report's pooled figures "
            "use 40 hypotheses on both models (the 70B's failed one left out of both, its "
            "never-broken ones counted as correct), so its rates differ slightly from these.", "",
            f"Permutation tests use {n['draws']} shuffles with seed {n['seed']}; 0.0001 means no "
            "shuffle reached the observed value. The variance and split-count tests take the upper "
            "tail of a statistic without direction; the paired permutations flip the sign of each "
            "change and are two-sided, as are all other tests.", ""]


def language_sections(runs):
    effect = [(r, " ".join(f"{k} {v:.2f}" for k, v in x["language_effect"]["rates"].items()),
               x["language_effect"]["cells_shuffled"]["p"],
               x["language_effect"]["answers_shuffled"]["p"]) for r, x in runs.items()]
    english = [(r, lang, t["odds_ratio"], with_holm(t), split(t["sign"]))
               for r, x in runs.items() for lang, t in x["english_vs"].items()]
    return [*section("1. Six-language effect: variance of the pooled language rates",
                     ["Shuffling whole cells keeps the three answers to a prompt together; "
                      "shuffling single answers treats them as independent."],
                     ["run", "rates", "p, prompt cells shuffled", "p, single answers shuffled"],
                     effect),
            *section("2. Each language against English, Holm over the five",
                     ["CMH is stratified by hypothesis but treats the answers within one as "
                      "independent; the sign test on the right counts hypotheses."],
                     ["run", "lang", "MH odds ratio", "CMH p", "hypotheses higher/lower"],
                     english)]


def truths_section(runs):
    rows, contrasts, same, logged = [], [], [], []
    for r, x in runs.items():
        named = [("premise, all hypotheses", x["different_truths"])]
        control = x.get("control_truths")
        if control:
            both = control["same_language_under_both"]
            named += [("premise, same hypotheses", control["premise_same_hypotheses"]),
                      ("neutral", control["neutral"]),
                      ("same language under both, cells shuffled", both)]
            same.append(f"`{r}` {both['observed']} against {both['expected']} expected "
                        f"(p {both['p']})")
            contrasts.append(f"`{r}` {split(control['split_in_one_only'], 'premise', 'neutral')}, "
                             f"{control['split_under_both']} under both")
            logged.append("{} of {}".format(*control["logged_rates_equal_raw_flags"]))
        rows += [(r, name, t["hypotheses"], t["observed"], t["expected"], t["p"])
                 for name, t in named]
    notes = ["The null shuffles single answers between the languages of a hypothesis. Within one "
             "condition, shuffling whole cells cannot change the count, which depends only on each "
             "hypothesis's set of cell totals; p here mostly measures how closely the answers to "
             "one prompt agree, which the cell ICC in item 7 shows too. Language and prompt are "
             "confounded.",
             "Both conditions show an excess over the single-answer null. Hypotheses split under "
             f"one condition only (premise/neutral, McNemar): {'; '.join(contrasts)}. A p above "
             "0.05 means no detectable difference between the conditions, not equal counts.",
             "The premise and neutral questions give each language two prompts, so one null keeps "
             "a prompt's answers together: in the last row of each run, one language is at 3/3 "
             "under both prompts and another at 0/3 under both, against shuffling whole cells "
             f"within each condition: {', '.join(same)}.",
             "control.json keeps only per-language rates of raw flags (equal to the replayed flags "
             f"in {', '.join(logged)} cells), so the control's verdicts are replayed from the LLM "
             "cache and counted like the findings."]
    return section("3. Different truths: one language at 3/3 and another at 0/3", notes,
                   ["run", "answers", "hypotheses", "observed", "expected", "p"], rows)


def hypothesis_section(runs):
    summary = []
    for r, x in runs.items():
        t = x["per_hypothesis"]
        summary.append((r, t["hypotheses"], len(t["below_alpha"]),
                        ", ".join(t["holm_below_alpha"]) or "none", t["tarone_family"],
                        ", ".join(t["tarone_below_alpha"]) or "none",
                        f"{t['floor_p']} (Holm {t['floor_p_holm']})"))
    below = [(r, b["hypothesis"], b["english"], b["others"], b["p"], b["p_holm"], b["p_tarone"])
             for r, x in runs.items() for b in x["per_hypothesis"]["below_alpha"]]
    doubts = [f"`{r}` {h}: {text}." for r, x in runs.items()
              for h, text in x["per_hypothesis"]["reading"].items()]
    first = next(iter(runs.values()))["per_hypothesis"]
    notes = [f"{first['test']}, of English (3 answers) against the other five languages (15) "
             "within each hypothesis. There English is one prompt answered three times and the "
             "others are five prompts, so a small p shows that one English prompt drew other "
             "answers than five other prompts, with the seeds as the only replication; it does not "
             "show a language effect. With whole cells shuffled, no hypothesis could reach p below "
             f"{first['cell_floor_p']}.",
             f"No split reaches p below {first['floor_p']}. Holm over all hypotheses "
             "multiplies that by their number (last column; above 0.05, none can survive). "
             "Hypotheses whose answers all agree can never reach significance; Tarone's family "
             "counts only those whose margins can reach alpha / m, and Bonferroni then divides "
             "alpha by that m.",
             " ".join(["The splits are the judge's verdicts.", *(
                 ["These need a human read before any is cited:", *doubts] if doubts else [])])]
    return [*section("6. English against the other five within each hypothesis", notes,
                     ["run", "hypotheses", "raw p < 0.05", "Holm over all, p < 0.05",
                      "Tarone family", "Tarone, p < 0.05", "smallest possible p"], summary),
            *grid_table(["run", "hypothesis", "English", "others", "p", "Holm", "Tarone"], below)]


def limit_sections(runs, report):
    rows = []
    for r, x in runs.items():
        t = x["detectable"]
        rows += [(r, t["english_rate"], f"{t['icc_hypothesis']} / {t['icc_cell']}", name,
                  t[name]["odds_ratio"], t[name]["pooled_rate_needed"],
                  t[name]["rate_at_mean_hypothesis"])
                 for name in ("one_hypothesis", "one_language_pooled")]
    listed = [(", ".join(map(str, c["lines"])) or "not found", c["reading"]["method"],
               c["reading"]["rests_on"], "yes" if c["reading"]["assumes_independence"] else "no")
              for c in report["claims"]]
    unlisted = ", ".join(map(str, report["unlisted_lines"])) or "none"
    return [*section("7. Minimum detectable effect against English, 80% power at alpha 0.05",
                     ["One hypothesis: 3 answers in one language against 15 in the others, "
                      "Fisher's exact test. Pooled: 3 against 3 in every hypothesis, rates drawn "
                      "from a beta distribution with the hypothesis ICC, CMH. The odds ratio holds "
                      "within each hypothesis and odds ratios do not average, so the pooled rate "
                      "a language needs is the mean over the drawn hypotheses, below the rate of a "
                      "hypothesis at the English mean. Answers are simulated as independent given "
                      "their hypothesis, but the three answers to a prompt agree more (cell ICC), "
                      "so these are lower bounds."],
                     ["run", "English rate", "ICC hypothesis / cell", "design", "odds ratio",
                      "pooled rate needed", "rate at the mean hypothesis"], rows),
            *section("8. Intervals and tests the report states",
                     ["Method and what it rests on are a reading written by hand; only the line "
                      f"numbers are computed. Unlisted lines that look like an interval: "
                      f"{unlisted}."],
                     ["report lines", "method", "rests on", "assumes independence"], listed)]


def markdown(n):
    return "\n".join([*preamble(n), *language_sections(n["runs"]), *truths_section(n["runs"]),
                      *mitigation_section(n["mitigation"]), *sizes_section(n["sizes"]),
                      *hypothesis_section(n["runs"]), *limit_sections(n["runs"],
                                                                      n["report_claims"])])
