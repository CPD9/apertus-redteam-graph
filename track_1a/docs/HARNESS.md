# Apertus Red-Team Graph — HackApertus Track 1A

An agent graph that red-teams Apertus v1.5 automatically across Swiss languages and turns
reproducible issues into schema-valid `findings/*.json`. (Challenge text: [../README.md](../README.md).)

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
| Judge | temperature-0 verdict against the hypothesis and a sourced reference |
| Verifier | reruns every language × seed, computes reproduction rates |
| Scribe | writes a finding that validates against `findings/findings.schema` |

## Run

| Command | What it does |
|---|---|
| `make run` | Docker, no GPU (what judges run): replays the canonical run from `data/llm_cache` (forces `REDTEAM_BACKEND=replay`, so no live server is called), validates every findings file, rebuilds the five findings from `data/runs` and fails on any difference with `findings/`, then prints the report's summary table |
| `make live` | Docker, a new run against the live servers (`LIVE_LLM_BASE_URL`, default `http://host.docker.internal:8000/v1`; `LIVE_RED_LLM_BASE_URL`, default `:8002/v1`; extra flags via `ARGS="--only <id>"`). Stops if a server does not answer, never replays, adds new calls to `data/llm_cache`, then validates the findings |
| `make dev` | `python -m redteam.run` locally without Docker: live endpoints if they answer, else replay, else MOCK (no check or rebuild) |
| `make dashboard` | live dashboard on http://127.0.0.1:8765 (graph, findings, persona studio) |
| `make test` | unit tests |

The target is reached only via `LLM_BASE_URL` / `LLM_NAME` / `LLM_API_KEY` (OpenAI-compatible, e.g.
vLLM serving `swiss-ai/Apertus-v1.5-8B` behind an SSH tunnel on `127.0.0.1:8000`), the attacker and
judge via `RED_LLM_BASE_URL` / `RED_LLM_NAME` / `RED_LLM_API_KEY` (Apertus 70B on `:8002`).
**If no endpoint answers, the harness replays from `data/llm_cache`; only with no endpoint and no
cache does it use a MOCK backend**: every event, finding title and note is labelled MOCK, and
`--promote` refuses to copy anything but live (vLLM) results into `findings/`.

Real runs write one file per reproduced hypothesis to `runs/<run_id>/findings/`. The submitted
findings group them by theme instead (`redteam.group --write`, `redteam.speech_finding --write`;
each finding's `steps_to_reproduce` gives the command), and `make run` fails on any file in
`findings/` that no generator writes, including files copied there with `--promote`.

## Agent avatars
The six agent avatars in `web/avatars/` were made with the Dot Avatar Maker studio
(`web/studio/dot-avatar-maker.html`). The dashboard's *Persona studio* tab embeds that studio so
anyone can redesign an agent and save it as its avatar. The studio loads three.js from jsDelivr
(UI only, no inference); vendor it for air-gapped use.

## Known issue in the template
`findings/findings.schema` from the official template contains a raw newline inside the
`topic_area` description string, so strict JSON parsers reject it. The harness parses it with
`strict=False`; worth reporting to the organizers.
