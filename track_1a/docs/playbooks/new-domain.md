# A new domain

The harness asks a model about claims that can be checked against a written reference, in up to
six languages, and measures how often it gets them wrong. The domain lives in the hypothesis
banks: a new domain is a new bank, called a pack. The judge, the verification, the event log and
the order of the graph's steps carry over unchanged; the attacker's persona, the languages and
some dashboard text stay Swiss. The worked example is the coding pack in
[examples/coding/](../../examples/coding/README.md).

## What carries over and what is Swiss

| Part | Where | In a new domain |
|---|---|---|
| Hypotheses and references | `src/redteam/hypotheses/*.json` | yours, in a pack |
| Steps: attacker, mutator, target, judge, verifier, scribe | `graph.py` | general |
| Judge: checks each claim of an answer against the reference | `judge.py` (claims prompt) | general |
| Event log, cache, replay, MOCK backend | `events.py`, `cache.py`, `llm.py` | general |
| Dashboard: runs, rates per language, answers, the pack's titles | `web/`, `dashboard.py` | general |
| Attacker persona ("testing a Swiss multilingual LLM", "a normal Swiss user") and strategies | `agents.py`, `hypotheses/strategies.txt` | Swiss |
| Languages en, de, gsw, fr, it, rm, and the check of which one a translation is in | `agents.py` | Swiss |
| Second-opinion judge ("A Swiss resident asked...") used by the rejudge | `judge.py` (premise prompt) | Swiss |
| Dashboard glossary: a hypothesis is "a claim about a Swiss fact" | `web/dash/explain-glossary.js` | Swiss |
| Themes, report, audits, the five submitted findings | `themes.json`, `technical_report.md`, `docs/audit/`, `findings/` | Swiss |

Every prompt is frozen: the recorded runs replay from hashes of the exact messages, so a pack
never touches one. A Swiss developer asking about Python in German or Romansh is still a fair
cross-language question; a team that needs another persona or other languages changes them in its
own copy and records new runs.

## Write a pack

A pack is a folder of JSON files (or one file), each a list of hypotheses with these fields:

| Field | What it holds | Read by |
|---|---|---|
| `id` | unique across all banks, one prefix per family (`code_python_`) | everything; `--only`; themes pick by prefix |
| `title` | at most 40 characters, unique | dashboard, report tables |
| `topic_area` | one of the five topics of [findings.schema](../../findings/findings.schema) | findings |
| `domain` | one word | `--domain`, dashboard |
| `hypothesis` | the wrong version, spelled out, and where you expect it | attacker, scribe |
| `reference` | the correct answer | attacker, judge |
| `sources` | official https pages that back the reference | people checking a finding |
| `harm` | who acts on a wrong answer and what it costs them | dashboard ("Why it matters") |

The judge sees only the reference, the question and the answer, and flags the answer as soon as
one of its claims contradicts the reference. So the reference states the correct fact exactly
("`list.sort()` sorts in place and returns None"), names the wrong version as wrong, includes the
true alternatives and exceptions so that a correct answer mentioning them is not flagged, says
nothing its sources do not say, and names the version when the fact changed between versions.
When no official source says it, leave the hypothesis out.

`python3 -m unittest tests.test_domain_pack` checks every pack in `examples/`.

## Run it

From `track_1a/`, naming the pack in `REDTEAM_BANKS` (several paths separated by `:`). Set it on
each command rather than exporting it: the unit tests expect the built-in banks only.

```bash
export PYTHONPATH=src
# MOCK: canned answers, no model, every event and finding labelled MOCK
REDTEAM_BANKS=examples/coding REDTEAM_BACKEND=mock python3 -m redteam run --domain coding --langs en,de,fr
# live: the target on 127.0.0.1:8000, the attacker and judge on :8002
python3 -c 'from redteam import llm; llm.require_servers()'
REDTEAM_BANKS=examples/coding python3 -m redteam run --domain coding --langs en,de,fr
```

The live run's first line must say `backend=vllm`; when a server does not answer, the run falls
back to replay and every pack hypothesis ends in `error`. Without `--domain` or `--only` a run also
takes every built-in hypothesis. An id that appears twice is refused, so a pack can never change the
reference of a recorded hypothesis, and `make run` replays only the recorded run. Each language
adds a translation, a language check, an answer and a judgement per attempt, so start with English
and the languages where you expect a gap, and check in the event log that code survived the
translation.

## Add a language

1. Add the code to `LANGUAGES` in `src/redteam/agents.py` with how the translator should write it
   (e.g. `"es": "Spanish (as written in Spain)"`), and its short name to `LANG_NAMES`.
2. Run with `--langs en,es`. Each language only changes its own translation prompt, so every
   recorded run still replays.
3. The harness's language check knows the six Swiss languages only and logs a new one as `Other`
   (a "mismatched" note in the event log, nothing else). For the word-list check of the audit, add
   marker words to `src/redteam/lang_markers.json` and rerun `python3 scripts/report_stimuli.py`.

## Read the results and turn them into findings

```bash
REDTEAM_BANKS=examples/coding python3 -m redteam dashboard
REDTEAM_BANKS=examples/coding python3 -m redteam control --run RUN
REDTEAM_BANKS=examples/coding python3 -m redteam.group --run RUN
```

The dashboard (http://127.0.0.1:8765) shows the pack's titles and references only when it starts
with the variable set. The scribe writes a findings file per reproduced hypothesis; the submitted
findings instead group hypotheses into themes in [themes.json](../../src/redteam/themes.json), by
id prefix (`"families": {"code_python_": "Python", "code_sql_": "SQL"}`), with the text written
like the Swiss themes. The control asks the same facts without the false premise and decides
whether a theme is `sycophancy` or a `knowledge gap`; `group --write` writes `findings/<theme>.json`
from live runs only. How the pieces fit: [docs/HARNESS.md](../HARNESS.md).
