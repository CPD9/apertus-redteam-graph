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
| `make run` | Docker: run the graph, then validate every findings file (what judges run) |
| `make dev` | same, locally without Docker |
| `make dashboard` | live dashboard on http://127.0.0.1:8765 (graph, findings, persona studio) |
| `make test` | unit tests |

The LLM is reached only via `LLM_BASE_URL` / `LLM_NAME` / `LLM_API_KEY` (OpenAI-compatible, e.g.
vLLM serving `swiss-ai/Apertus-v1.5-8B` behind an SSH tunnel on `127.0.0.1:8000`).
**If no endpoint answers, the harness uses a MOCK backend**: every event, finding title and note is
labelled MOCK, and `--promote` refuses to copy mock results into `findings/`.

Real runs write to `runs/<run_id>/findings/`; after human review,
`python -m redteam.run --promote` copies them into `findings/` for submission.

## Agent avatars
The six agent avatars in `web/avatars/` were made with the Dot Avatar Maker studio
(`web/studio/dot-avatar-maker.html`). The dashboard's *Persona studio* tab embeds that studio so
anyone can redesign an agent and save it as its avatar. The studio loads three.js from jsDelivr
(UI only, no inference); vendor it for air-gapped use.

## Known issue in the template
`findings/findings.schema` from the official template contains a raw newline inside the
`topic_area` description string, so strict JSON parsers reject it. The harness parses it with
`strict=False`; worth reporting to the organizers.
