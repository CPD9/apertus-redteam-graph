"""What each agent of the graph can do and what it has learned, computed from the recorded runs
(agent_facts) and the audits in docs/audit/, never written by hand: every value names its count,
its denominator and the file it comes from. One function per agent, keyed by its id in MINERS.
"""
from __future__ import annotations

from pathlib import Path

from .agent_facts import RunFacts, dig, evidence, learning, of, skill, strength
from .agents import LANG_NAMES, STRATEGIES
from .graph import Config

CALIBRATION, SCORER = "docs/audit/calibration.json", "docs/audit/scorer.json"
STIMULI, STATS = "docs/audit/stimuli.json", "docs/audit/stats.json"


def attacker(runs: list[RunFacts], audits: dict) -> tuple[list, list]:
    order = [name for name, _ in STRATEGIES]  # the graph tries them in this order
    names = order + sorted({n for r in runs for n in r.strategies} - set(order))
    skills, learnings = [], []
    for name in names:
        tried = [(r, r.strategies[name]) for r in runs if name in r.strategies]
        title = name.replace("_", " ").capitalize()
        attempt = f" (attempt {order.index(name) + 1})" if name in order else ""
        if landed := [r for r, s in tried if s.landed]:
            skills.append(skill(
                f"strategy-{name}", title + attempt, dict(STRATEGIES).get(name, ""),
                [evidence(f"{r.name}: taken to the verifier",
                          f"{of(s.verified, r.hypotheses, 'hypotheses')}; {s.reproduced} of them "
                          "reproduced", r.source) for r, s in tried], landed[0].id, landed[0].date))
        elif tried:
            attempts = sum(s.attempts for _, s in tried)
            learnings.append(learning(
                f"{title} never produced an answer that counts: none in {attempts} attempts "
                f"over {len(tried)} runs.",
                [evidence(f"{r.name}: attempts with an answer that counts",
                          of(0, s.attempts, "attempts"), r.source) for r, s in tried],
                tried[-1][0].id, tried[-1][0].date))
    used = [(r, r.strategies[order[0]]) for r in runs if order[0] in r.strategies]
    if used:
        taken, kept = (sum(getattr(s, key) for _, s in used) for key in ("verified", "reproduced"))
        learnings.append(learning(
            f"{order[0].replace('_', ' ').capitalize()} breaks the most: over {len(used)} runs "
            f"it took {of(taken, sum(r.hypotheses for r, _ in used), 'hypotheses tried')} to the "
            f"verifier, and {of(kept, taken)} of those reproduced under the counting rule. A "
            "flagged answer is a lead, not a finding.",
            [evidence(r.name, f"{s.verified} taken on, {s.reproduced} reproduced", r.source)
             for r, s in used], used[-1][0].id, used[-1][0].date))
    return skills, learnings


def mutator(runs: list[RunFacts], audits: dict) -> tuple[list, list]:
    langs = list(dict.fromkeys(lang for r in runs for lang in r.langs))
    skills = [skill("six-languages", f"{len(langs)} languages",
                    "Translates every attack into " + ", ".join(LANG_NAMES[l] for l in langs)
                    + ", keeping names, numbers and intent.",
                    [evidence(r.name, f"{r.prompts} translations into {len(r.langs)} languages",
                              r.source) for r in runs], runs[0].id, runs[0].date)]
    # per language: prompts, read as asked by the word list, flagged by the harness, by the list
    learnings, tally = [], {}
    for run in (dig(audits.get("stimuli"), "prompts") or {}).values():
        for lang, f in run.get("flags", {}).items():
            row = [f["prompts"], run["word_list"].get(lang, {}).get(lang, 0), f["harness"],
                   f["word_list"]]
            tally[lang] = [a + b for a, b in zip(tally.get(lang, [0] * 4), row)]
    if tally:
        skills.append(skill(
            "writes-the-asked-language", "Writes the language asked for",
            "A word-list check that uses no model reads nearly every translation as the "
            "language it was asked for.",
            [evidence(LANG_NAMES.get(lang, lang), of(right, n, "prompts read as asked"), STIMULI)
             for lang, (n, right, _, _) in tally.items()], STIMULI))
    for lang, (n, _, harness, words) in tally.items():
        name = LANG_NAMES.get(lang, lang)
        if n and harness >= 0.1 * n and words <= 0.1 * n:
            learnings.append(learning(
                f"The harness's own language check calls {of(harness, n)} {name} prompts "
                f"another language; the word list disagrees with {of(words, n)}. In {name} the "
                "check is what errs, not the translation.",
                [evidence("flagged by the harness's language check", of(harness, n, "prompts"),
                          STIMULI),
                 evidence("flagged by the word list", of(words, n, "prompts"), STIMULI)],
                STIMULI))
    return skills, learnings


def judge(runs: list[RunFacts], audits: dict) -> tuple[list, list]:
    skills, learnings = [], []
    if acc := dig(audits.get("calibration"), "both_runs_accuracy", "all"):
        se, sp = acc["sensitivity"], acc["specificity"]
        skills.append(skill(
            "catches-wrong-values", "Catches a wrong number",
            "Counts the answers that state a wrong value and passes most that state the right "
            "one, measured against a numeric scorer that uses no model.",
            [evidence("answers stating only the wrong value that I count",
                      of(se["k"], se["n"], "answers"), CALIBRATION),
             evidence("answers stating only the right value that I pass",
                      of(sp["k"], sp["n"], "answers"), CALIBRATION)], CALIBRATION))
    if kappa := dig(audits.get("scorer"), "pooled", "all", "both_as_no"):
        lo, hi = kappa["ci95"]
        skills.append(skill(
            "agrees-with-scorer", "Agrees with the numeric scorer",
            f"Agrees {strength(kappa['kappa'])} with the scorer on the answers both can read.",
            [evidence("Cohen's kappa with the scorer", f"{kappa['kappa']:.2f} over "
                      f"{kappa['n']} answers (95% CI {lo:.2f} to {hi:.2f})", SCORER)], SCORER))
    per_lang = dig(audits.get("calibration"), "both_runs_accuracy", "per_lang") or {}
    for lang, cell in per_lang.items():
        se, sp = cell["sensitivity"], cell["specificity"]
        if cell["youden"] < 0.5:
            learnings.append(learning(
                f"I am unreliable in {LANG_NAMES.get(lang, lang)}: I count {of(se['k'], se['n'])} "
                f"answers with a wrong value and pass {of(sp['k'], sp['n'])} with the right one "
                f"(Youden index {cell['youden']:.2f}). Read my verdicts in it with care.",
                [evidence("sensitivity", of(se["k"], se["n"], "answers"), CALIBRATION),
                 evidence("specificity", of(sp["k"], sp["n"], "answers"), CALIBRATION)],
                CALIBRATION))
    second = [(r, audits["rejudge"][r.id]) for r in runs if r.id in audits.get("rejudge", {})]
    if second:
        learnings.append(learning(
            "A second judge, worded independently, agrees with me "
            + " and ".join(dict.fromkeys(strength(j["kappa"]) for _, j in second)) + " ("
            + "; ".join(f"kappa {j['kappa']:.2f} over {j['n']} verdicts in the {r.name}"
                        for r, j in second) + "). Where we split, the verdict is not settled.",
            [evidence(r.name, f"kappa {j['kappa']:.2f}, raw agreement "
                      f"{of(round(j['raw_agreement'] * j['n']), j['n'], 'verdicts')}",
                      Path(r.source).with_name("rejudge.json")) for r, j in second],
            second[-1][0].id, second[-1][0].date))
    return skills, learnings


def verifier(runs: list[RunFacts], audits: dict) -> tuple[list, list]:
    seeds = ", ".join(map(str, runs[0].seeds))
    skills = [
        skill("three-seeds", f"{len(runs[0].seeds)} seeds per language",
              f"Reruns every language variant with the seeds {seeds} and has each answer judged.",
              [evidence(r.name, f"{r.counted.n} answers judged, from {r.tested} hypotheses in "
                        f"{len(r.langs)} languages with {len(r.seeds)} seeds", r.source)
               for r in runs], runs[0].id, runs[0].date),
        skill("counting-rule", "Counts only what holds up",
              f"A hypothesis reproduces when at least {Config.min_rate:.0%} of its answers "
              "count: flagged by the judge and rated above 0.",
              [evidence(r.name, of(r.reproduced, r.hypotheses, "hypotheses reproduced"), r.source)
               for r in runs], runs[0].id, runs[0].date)]
    learnings = []
    cells = [(r, dig(audits.get("stats"), "runs", r.id)) for r in runs]
    cells = [(r, s) for r, s in cells if dig(s, "detectable", "icc_cell") is not None]
    if cells:
        learnings.append(learning(
            "The three answers to one prompt mostly agree (within-prompt correlation "
            + ", ".join(f"{s['detectable']['icc_cell']:.2f} in the {r.name}" for r, s in cells)
            + "), so three seeds weigh less than three independent answers.",
            [evidence(r.name, f"ICC {s['detectable']['icc_cell']:.3f} over "
                      f"{s['coverage']['hypotheses']} hypotheses", STATS) for r, s in cells],
            STATS))
    return skills, learnings


def target(runs: list[RunFacts], audits: dict) -> tuple[list, list]:
    skills, learnings = [], []
    plain = [r for r in runs if not r.system and r.counted.n]
    for r in plain:
        ranked = sorted(r.per_lang, key=lambda lang: r.per_lang[lang].rate)
        low, high = r.per_lang[ranked[0]], r.per_lang[ranked[-1]]
        learnings.append(learning(
            f"My errors depend on the language: in the {r.name}, "
            f"{of(low.k, low.n, 'answers')} count in {LANG_NAMES[ranked[0]]} and "
            f"{of(high.k, high.n)} in {LANG_NAMES[ranked[-1]]}.",
            [evidence(LANG_NAMES[lang], of(s.k, s.n, "answers count"), r.source)
             for lang, s in r.per_lang.items()], r.id, r.date))
    lowest = {min(r.per_lang, key=lambda lang: r.per_lang[lang].rate) for r in plain}
    if len(lowest) == 1:
        lang = lowest.pop()
        skills.append(skill(
            f"most-accurate-in-{lang}", f"Most accurate in {LANG_NAMES[lang]}",
            f"In every run without a system prompt, the fewest of my answers count in "
            f"{LANG_NAMES[lang]}.",
            [evidence(r.name, of(r.per_lang[lang].k, r.per_lang[lang].n, "answers count"),
                      r.source) for r in plain], plain[0].id, plain[0].date))
    small = next((r for r in plain if "8B" in r.model), None)
    large = next((r for r in plain if "70B" in r.model), None)
    if small and large:
        fewer = "fewer" if large.counted.rate < small.counted.rate else "no fewer"
        learnings.append(learning(
            f"At 70B I make {fewer} counted errors than at 8B: "
            f"{of(large.counted.k, large.counted.n)} answers against "
            f"{of(small.counted.k, small.counted.n)}.",
            [evidence(r.name, of(r.counted.k, r.counted.n, "answers count"), r.source)
             for r in (small, large)], large.id, large.date))
    if per_lang := dig(audits.get("stats"), "mitigation", "per_lang"):
        pairs = audits["stats"]["mitigation"]["pairs"]
        before, after = (sum(c[key] for c in per_lang.values()) for key in ("without", "with"))
        each = pairs // len(per_lang)  # every language has the same hypotheses and seeds
        rose = [lang for lang, c in per_lang.items() if c["with"] > c["without"]]
        skills.append(skill(
            "heeds-a-system-prompt", "Heeds a system prompt",
            "Told to check the question's premise before answering, I confirm far fewer false "
            "claims on the same prompts.",
            [evidence("answers that count without the prompt", of(before, pairs, "answers"), STATS),
             evidence("with the prompt", of(after, pairs, "answers"), STATS)], STATS))
        for lang in rose:
            c = per_lang[lang]
            learnings.append(learning(
                f"The mitigation prompt did not help in {LANG_NAMES[lang]}: answers that count "
                f"rose from {of(c['without'], each)} to {of(c['with'], each)} on the same prompts.",
                [evidence(f"{lang} without the prompt", of(c["without"], each, "answers"), STATS),
                 evidence(f"{lang} with the prompt", of(c["with"], each, "answers"), STATS)],
                STATS))
    return skills, learnings


MINERS = {"attacker": attacker, "mutator": mutator, "target": target, "judge": judge,
          "verifier": verifier}  # the scribe's are in agent_skills, which rebuilds the findings
