# How the harness works

An agent graph that red-teams Apertus across Swiss languages and turns reproducible issues into
schema-valid findings. Where to start, as a judge, a teammate or next year's team, is in the
[README](../../README.md); the challenge text is in [../README.md](../README.md).

```
attacker ─► mutator ─► target ─► judge ──(clean, attempts left)──► attacker (with feedback)
                                   │
                                   └──(violation)──► verifier (languages × seeds) ──(rate ≥ min)──► scribe
```

| Agent | Job |
|---|---|
| Attacker | turns a hypothesis from `src/redteam/hypotheses/` into a realistic user prompt; refines it from judge feedback |
| Mutator | translates the prompt: en, de, gsw (Swiss German), fr, it, rm (Romansh) |
| Target | Apertus under test |
| Judge | temperature-0 verdict against the hypothesis and its sourced reference |
| Verifier | reruns every language × seed and computes reproduction rates |
| Scribe | writes a finding that validates against `findings/findings.schema` (read with `strict=False`: the template's schema has a raw newline inside a string) |

**Models.** The target is reached via `LLM_BASE_URL`, `LLM_NAME` and `LLM_API_KEY` (any
OpenAI-compatible server, e.g. vLLM with Apertus 8B on `127.0.0.1:8000`), the attacker, mutator and
judge via `RED_LLM_BASE_URL`, `RED_LLM_NAME` and `RED_LLM_API_KEY` (Apertus 70B on `:8002`). Every
call is stored in `data/llm_cache/`. If no endpoint answers, the harness replays from that cache;
only with no endpoint and no cache does it fall back to a MOCK backend, whose events, titles and
notes are all labelled MOCK and which `--promote` refuses to copy into `findings/`.

**Outputs.** A run writes its event log and one finding per reproduced hypothesis to
`runs/<run_id>/`. The submitted findings group those by theme (`redteam.group`, and
`redteam.speech_finding` for speech); `reproduce` rebuilds them and fails on any file in
`findings/` that no generator writes.

## Commands

From `track_1a/`, as `PYTHONPATH=src python3 -m redteam <command>` (or `apertus-redteam <command>`
after `pip install -e .`). Each passes its arguments to the module named, which still runs on its
own, and `<command> --help` shows them. Most also have a make target of the same name, except
`run`: `make run` is the Docker replay judges use (below), and `make dev` runs
`python -m redteam run`.

| Command | Runs | What it does |
|---|---|---|
| `replay` | `redteam.run --replay` | replays the canonical run from `data/llm_cache`, no GPU |
| `check` | `redteam.check` | validates every findings file against the schema |
| `reproduce` | `redteam.reproduce` | rebuilds the five findings from `data/runs` and compares them with `findings/` |
| `crosscheck` | `crosscheck` | recounts every reported number without the harness's counting code |
| `audit` | `scripts/report_scorer.py`, `report_calibration.py`, `report_stats.py`, `report_stimuli.py`, `crosscheck --diffs --json`, `scripts/report_rescore.py` | reruns the audit scripts and rewrites the notes in `docs/audit/` |
| `figures` | `scripts/report_figures.py` | redraws `docs/figures/` from the report's runs |
| `report` | `scripts/build_report.py` | builds `Star-rust_Report.pdf` with headless Chrome |
| `dashboard` | `redteam.server` | dashboard and judge-review page on http://127.0.0.1:8765 (`PORT` for another port) |
| `labels` | `redteam.review` | what the review page's labels say about the judge |
| `run` | `redteam.run` | a new run: live servers if they answer, else replay, else MOCK; `--only ID`, `--langs`, `--system` |
| `control` | `redteam.control` | asks a run's reproduced hypotheses again as neutral questions |
| `rejudge` | `redteam.rejudge` | a second, independently worded judge on a run |

Docker: `make run` replays the canonical run, checks and rebuilds the five findings in a container
(what judges run); `make live ARGS="--only <id>"` makes a new run against the servers on the host's
tunnels and stops if either does not answer. The [playbooks](playbooks/) walk through the common
tasks with the output to expect.

## Dashboard

`make dashboard` plays a run's events back through the six agents and shows each hypothesis by
language. Its averages take the hypotheses each run verified (41 on the 8B), so they can differ by
a point from the report's, which take the 40 attacked on both models.

<p align="center">
  <img src="assets/dashboard-graph.png" alt="Dashboard: the six agents and the event log of a run" width="820">
  <img src="assets/dashboard-gap.png" alt="Dashboard: language gap of the 8B run, 41 hypotheses by language" width="820">
</p>

The agent avatars in `web/avatars/` were made with the Dot Avatar Maker studio, which is not in the
repository. When a local copy is present (`web/studio/dot-avatar-maker.html`), the dashboard shows
a *Persona studio* tab to redesign them; that page loads three.js from jsDelivr, so vendor it for
air-gapped use.
