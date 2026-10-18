"""The stimulus language note (docs/audit/stimuli.md) from the numbers in stimuli.json."""
from __future__ import annotations

INTRO = """**This is a heuristic word-list check, not a native speaker's judgement.** \
`src/redteam/lang_profile.py` counts in each text the marker words of \
`src/redteam/lang_markers.json` ({markers}): function words and spellings typical of one \
language and rare in the others; each list says what it leaves out and why. Every marker is one \
vote and the language with most votes wins. A text is uncertain when it has fewer than \
{min_votes} votes, or when its winner leads the runner-up by fewer than {min_lead} votes or by \
less than {min_margin} of all votes. The lists never ask a model, but they were pruned on the \
prompts and the answers of sections 1 to 4: words that voted against a text's main language were \
taken out. Their agreement there is therefore optimistic; section 5 measures it on answers they \
were not pruned on. The check sees only the listed words: German or Italian words borrowed into a \
Swiss German or Romansh sentence, calques, a regional idiom or stilted phrasing pass unseen, and \
words inside a quotation count like any other, so a quoted German line votes German.

The harness's own check (`agents.language_check`, logged as "detected" with each translation) asks \
Apertus 70B, the model that translated the prompts, to name their language."""

NATIVE = """## What a native speaker should look at

- The prompts listed in section 2, then those the harness check puts in another language and the \
word list does not (section 1): only a native reading can say which check is wrong.
- Every Swiss German prompt: Zurich dialect as people text it, or Standard German respelled \
(Standard word order and tenses, "Stimmt es, dass")?
- Every Romansh prompt: Rumantsch Grischun throughout, or mixed with a regional idiom (ün, o and \
cha are Engadin forms) or with Italian or German words the word list cannot see?
- Whether each translation keeps the premise: the same numbers, names and false claim in all six \
languages.
- The answers listed in section 4: Standard German or Italian, or a mixture the word list reads \
one way?
- The Romansh and Swiss German answers that count as wrong: whether the answer is wrong, or the \
prompt's wording asked something else."""


def table(head, rows):
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head),
            *("| " + " | ".join(str(x).replace("|", "/") for x in row) + " |" for row in rows)]


def counts(found):
    return ", ".join(f"{lang} {n}" for lang, n in found.items()) or "none"


def interval(cell, sign=""):
    if not cell.get("ci95"):
        return "–"
    lo, hi = cell["ci95"]
    return f"{cell['rate']:{sign}.2f} ({lo:{sign}.2f} to {hi:{sign}.2f}), {cell['hypotheses']}"


def header(numbers):
    models, system = numbers["models"], numbers["system_prompt"]
    named = {key: ", ".join(f"`{run}` {models.get(run, '')}".strip() for run in run_ids)
             or "none" for key, run_ids in numbers["runs"].items()}
    with_system = f"; {', '.join(system)} ran with a system prompt" if system else ""
    return ["# Stimulus language audit", "",
            f"Written by `{numbers['script']}`; every number is in `stimuli.json`. Prompts: "
            f"{named['prompts']}. Answers: {named['answers']}. Answers the word list was not "
            f"pruned on: {named['held_out']}{with_system}."]


def prompts_section(numbers):
    by_run, total = numbers["prompts"], numbers["prompts_total"]
    logged = total["prompts"] - total["unlogged"]
    checked = f" of the {logged} it checked" if total["unlogged"] else ""
    harness = (f"the harness check puts {total['harness']}{checked} in another language, "
               f"{total['english_called_german']} of them English prompts it calls German"
               if logged else "no harness check is logged")
    return [
        "## 1. Prompts: intended language against each check", "",
        *table(["run", "intended", "word list", "harness check", "both put it elsewhere"],
               [(run_id, lang, counts(found), counts(read["harness"][lang]),
                 read["flags"][lang]["both"])
                for run_id, read in by_run.items() for lang, found in read["word_list"].items()]),
        "", f"Of all {total['prompts']} prompts in the table, {harness}; the word list "
        f"puts {total['word_list']} in another language and is uncertain about "
        f"{total['uncertain']}, and both checks put {total['both']} in another language."]


def listed_section(numbers):
    rule, entries = numbers["listing"], numbers["listed"]
    found = rule["read_as_pair"]
    rows = [(entry["hypothesis"], ", ".join(run[-4:] for run in entry["runs"]), entry["lang"],
             entry["words"], counts(entry["votes"]),
             "" if entry["pair_share"] is None else entry["pair_share"], entry["harness"],
             entry["excerpt"]) for entry in entries]
    return [
        "## 2. Swiss German that reads as Standard German, Romansh that reads as Italian", "",
        f"Swiss German prompts the word list reads as Standard German: {found['gsw']}. Romansh "
        f"prompts it reads as Italian: {found['rm']}. Listed: every "
        "distinct prompt in which another language has more marker words than the intended one, "
        "whether or not enough to name it, and every Swiss German or Romansh prompt whose pair "
        f"language (de, it) has at least {rule['pair_votes_min']} votes and at least "
        f"{rule['pair_share_min']:.2f} of the pair's votes (pair share).", "",
        *(table(["hypothesis", "runs", "intended", "word list", "votes", "pair share", "harness",
                 "excerpt"], rows) if rows else ["No prompt is listed."])]


def gap_line(run_id, by_filter):
    above, below, empty = [], [], []
    for name, cell in by_filter.items():
        gap = cell["rm_minus_en"]
        (empty if "ci95" not in gap else above if gap["ci95"][0] > 0 else below).append(name)
    if not above and not below:
        return f"- {run_id}: no Romansh answers to compare with English."
    parts = [f"the interval of the Romansh gap lies above 0 with {', '.join(above) or 'no filter'}"]
    if below:
        parts.append(f"its lower end is 0 or below with {', '.join(below)}")
    if empty:
        parts.append(f"no Romansh prompt is left with {', '.join(empty)}")
    return f"- {run_id}: " + "; ".join(parts) + "."


def word_list_line(by_run):
    moved = {run_id: {lang: n for lang, n in by_filter["word list kept"]["left_out"].items()
                      if lang in ("gsw", "rm")} for run_id, by_filter in by_run.items()}
    if not any(moved.values()):
        return ("The word list puts no Swiss German or Romansh prompt of these runs in another "
                "language, so their rates and the Romansh gap are the same with all prompts and "
                "with word list kept.")
    return ("Swiss German and Romansh prompts the word list leaves out: "
            + "; ".join(f"{run_id} {counts(m)}" for run_id, m in moved.items() if m) + ".")


def rates_section(numbers):
    by_run = numbers["rates"]
    filters = list(next(iter(by_run.values()), {}))
    rows, left = [], []
    for run_id, by_filter in by_run.items():
        rows += [(run_id, lang, *(interval(by_filter[name]["per_lang"].get(lang, {}))
                                  for name in filters))
                 for lang in by_filter[filters[0]]["per_lang"]]
        rows.append((run_id, "rm − en", *(interval(by_filter[name]["rm_minus_en"], "+")
                                          for name in filters)))
        left.append((run_id, *(counts(by_filter[name]["left_out"]) for name in filters[1:])))
    return [
        "## 3. Counted wrong-answer rates without the prompts either check puts elsewhere", "",
        "All prompts: every prompt. Word list kept: leaves out the prompts the word list puts in "
        "another language; those it is uncertain about stay. Harness kept: leaves out the prompts "
        "the harness check names another language, or a language outside the six; prompts without "
        "a logged check stay. Answers count by Answer.confirmed, over the hypotheses with verified "
        "answers. Each cell: rate (95% interval), hypotheses; intervals from "
        f"{numbers['bootstrap']['draws']} bootstrap draws over hypotheses, seed "
        f"{numbers['bootstrap']['seed']}. The rm − en gap filters the Romansh prompts only and "
        "compares them with English on the same hypotheses.", "",
        *table(["run", "lang", *filters], rows), "", "Prompts each filter leaves out:", "",
        *table(["run", *filters[1:]], left), "", word_list_line(by_run), "",
        *(gap_line(run_id, by_filter) for run_id, by_filter in by_run.items())]


def answers_section(numbers):
    lines = ["## 4. The language of the answers", "", *table(
        ["run", "prompt", "answers", "answer language (word list)", "median characters",
         "median words"],
        [(run_id, lang, cell["answers"], counts(cell["languages"]), f"{cell['median_chars']:g}",
          f"{cell['median_words']:g}") for run_id, by_lang in numbers["answers"].items()
         for lang, cell in by_lang.items()])]
    for run_id, by_lang in numbers["answers"].items():
        said = [f"{lang} prompts answered in {pair}: {cell['languages'].get(pair, 0)} of "
                f"{cell['answers']}" for lang, pair in numbers["listing"]["pairs"].items()
                if (cell := by_lang.get(lang))]
        if said:
            lines += ["", f"{run_id}: " + "; ".join(said) + "."]
    listed = numbers["answers_listed"]
    if listed:
        lines += ["", "Those answers, each with the votes that read it as the pair language "
                  "(counted: whether it counts as a wrong answer):", "", *table(
                      ["run", "hypothesis", "prompt", "seed", "votes", "counted", "excerpt"],
                      [(entry["run"][-4:], entry["hypothesis"], entry["lang"], entry["seed"],
                        counts(entry["votes"]), "yes" if entry["counted"] else "no",
                        entry["excerpt"]) for entry in listed])]
    return lines


def held_out_section(numbers):
    held = numbers["held_out"]
    if not held["answers"]:
        return []
    total = held["total"]
    return [
        "## 5. The word list on answers it was not pruned on", "",
        "The lists were pruned on the texts of sections 1 to 4, not on these answers. Six words "
        "(has, han, as, ans, gea, einfach) were taken out after these answers had been read once, "
        "so they are not wholly unseen.", "",
        *table(["run", "prompt", "answers", "answer language (word list)"],
               [(run_id, lang, cell["answers"], counts(cell["languages"]))
                for run_id, by_lang in held["answers"].items() for lang, cell in by_lang.items()]),
        "", f"The word list puts {total['prompt_language']} of {total['answers']} answers in their "
        f"prompt's language, is uncertain about {total['uncertain']} and puts {total['elsewhere']} "
        "in another language. Each of those is an answer written in another language or a "
        "misreading, so their share bounds from above how often the list misreads an answer "
        "written in its prompt's language; it cannot show a misreading that agrees with the "
        "prompt's language."]


def markdown(numbers):
    word_list = numbers["word_list"]
    intro = INTRO.format(**{**word_list, "markers": counts(word_list["markers"])})
    sections = [header(numbers), [intro], prompts_section(numbers), listed_section(numbers),
                rates_section(numbers), answers_section(numbers), held_out_section(numbers),
                [NATIVE]]
    return "\n\n".join("\n".join(section) for section in sections if section) + "\n"
