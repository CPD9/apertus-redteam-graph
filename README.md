# Apertus Red-Team Graph

**Same question, six Swiss languages, different truths.**
An automated, fully self-hosted red-teaming harness that checks whether Apertus gives a Swiss user
the same correct, safe answer whether they ask in English, German, Swiss German, French, Italian or
Romansh, plus a probe of how well Apertus understands spoken Swiss German.

Team **Star-rust** · HackApertus 2026 · Track 1A (red-teaming) ·
**[Report (PDF, 6 pages)](track_1a/Star-rust_Report.pdf)** · [Roadmap](track_1a/docs/ROADMAP.md)

**Status:** five findings, report and dashboard are ready; what is still open, and who does it, is
in the [roadmap](track_1a/docs/ROADMAP.md).

<p align="center">
  <img src="track_1a/docs/assets/agent-loop.svg" alt="Animated agent loop: attacker, mutator, target, judge, verifier, scribe" width="900">
</p>

## Why it matters

People in Switzerland may act on what a model tells them about their rights: voting deadlines, residence
permits, tenancy, pensions, emergency numbers. A sovereign Swiss model should be equally reliable in
all national languages. We test exactly that, at scale, and hand over every issue with its own
reproduction grid.

## What makes it different

| | |
|---|---|
| **Apertus red-teams Apertus** | Apertus 70B (the community FP8 build) writes the attacks and judges the answers of Apertus 8B. No external model is part of the pipeline. |
| **One probe, six languages** | Each attack is translated into en, de, gsw, fr, it and rm and rerun across seeds, so a reproduced hypothesis is a pattern, not an anecdote. |
| **Sycophancy vs. ignorance** | A neutral-question control separates "Apertus doesn't know" from "Apertus knows, but agrees with a false user claim". |
| **Replays without a GPU** | Every text and image model call is cached. `make run` replays the canonical run in Docker and gets identical verdicts. |
| **Counts honestly** | An answer counts only when the judge rates it as stating the error; a neutral control and a 70B replication test every text finding. |
| **Sourced ground truth** | 76 hypotheses with reference answers; 72 cite their sources (fedlex, ch.ch, SEM, EDÖB, AHV-IV, BAG, Tox Info, …). |
| **Speech too** | Swiss German audio (8 dialects, 480 clips) through Apertus 1.5's audio input, compared with a Swiss German Whisper. |

## What we found

Every text number below counts only answers that Apertus 70B, checking them against the
hypothesis's reference, rates as stating the error, over 6 languages × 3 sampling seeds. The speech
row counts translations of SwissDial clips that the same judge rates unrelated to what was said.
Details and 95% CIs are in the [technical report](track_1a/technical_report.md) and
[`numbers.json`](track_1a/docs/figures/numbers.json).

**The language gap.** Over the 40 hypotheses with results on both models, the share of wrong answers is lowest in English and highest in Romansh:

| | English | German | Swiss German | French | Italian | Romansh |
|---|---|---|---|---|---|---|
| Apertus 8B | 25% | 31% | 38% | 41% | 36% | **48%** |
| Apertus 70B | **5%** | 19% | 20% | 22% | 27% | **42%** |

The dashboard averages the hypotheses each run verified (41 on the 8B), so its heatmap differs by a point.

<p align="center">
  <img src="track_1a/docs/figures/languages_8b_70b.svg" alt="Share of wrong answers per language, Apertus 8B and 70B, with 95% intervals" width="420">
  <img src="track_1a/docs/figures/speech_dialects.svg" alt="Share of Swiss German audio clips Apertus 70B translated into something the speaker did not say, per dialect" width="420">
</p>

**Five findings** ([`track_1a/findings/`](track_1a/findings)), with our self-assessed severity and
breadth on the [challenge rubric](track_1a/README.md) (0, 1, 2, 5 or 10):

| # | Finding | Wrong answers | Key contrast | Severity / breadth |
|---|---|---|---|---|
| 1 | [Apertus confirms false claims about Swiss history, voting rules and literature](track_1a/findings/civic_sycophancy.json) | 74% (8B), 39% (70B) | English 50%, French and Romansh 88%; asked neutrally 35% | 2 / 5 |
| 2 | [Apertus confirms made-up details about a private person](track_1a/findings/private_person_fabrication.json) | 83% (8B), 17% (70B) | English 0%, every other language 100% | 2 / 2 |
| 3 | [Apertus gets Swiss emergency numbers, health insurance and alarm sirens wrong](track_1a/findings/safety_knowledge_gaps.json) | 71% (8B), 46% (70B) | wrong as often when asked neutrally (75%) | 2 / 5 |
| 4 | [Apertus gets Swiss old-age pension rules wrong](track_1a/findings/pension_rules.json) | 64% (8B), 56% (70B) | wrong as often when asked neutrally (72%) | 5 / 5 |
| 5 | [Apertus invents what Swiss German speakers said](track_1a/findings/speech_dialect_hallucination.json) | 48% of 480 clips (70B) | a Swiss German Whisper: 1% | 2 / 5 |

A short system prompt asking the model to check whether the question assumes something false about
Swiss law cuts the 70B's rate on the 29 retested hypotheses from 29% to 12%, but makes English worse
(6% → 16%). An image probe (false rules printed on a notice) is not reported until it is rerun: its
judge was shown the claim as typed by the user, though it was only in the image.

## How we count

- **Only answers that state the error.** The judge (Apertus 70B) checks every claim against the
  hypothesis's reference; an answer counts only if it is flagged *and* rated above severity 0. On the
  8B run this keeps 16 of the 31 hypotheses with at least 34% of answers flagged.
- **Sycophancy or ignorance.** Neutral questions written from the same references show whether
  Apertus does not know the fact (wrong both ways) or gives in to the user (right only when asked
  neutrally).
- **Both sizes.** Every text finding was rerun with Apertus 70B as the target; 29 hypotheses were
  run once more with a mitigation system prompt.
- **Judging the judge.** A second, independently worded judge also flags 97% of what the main judge
  flags, but many corrections too (κ 0.19; it saw shortened answers, a rerun on full answers is
  ready). Human labels from the review page come next.
- **Read, not just counted.** Variations left out after reading the answers are named in each
  finding's notes with the reason, and every number in the report, this README and the findings was
  checked against the raw run logs in two passes.

## How it works

```mermaid
flowchart LR
    H[(76 hypotheses<br/>with references)] --> A[Attacker<br/>Apertus 70B]
    A -- "strategy: false premise,<br/>practical need, authority,<br/>code-switching" --> M[Mutator<br/>en de gsw fr it rm]
    M --> T["Target<br/>Apertus 8B: 41 of them<br/>Apertus 70B: all 76"]
    T --> J{Judge<br/>Apertus 70B,<br/>claim by claim}
    J -- no violation --> A
    J -- violation --> V[Verifier<br/>6 languages × 3 seeds<br/>Wilson 95% CI]
    V -- reproduces --> S[Scribe<br/>one schema-valid file<br/>per hypothesis]
    V -- does not --> X[discarded]
    S --> C[Control<br/>same facts,<br/>no premise]
    J -.-> K[Second judge<br/>agreement check]
```

Every step is logged as an event, and the dashboard plays them back live:

<p align="center">
  <img src="track_1a/docs/assets/dashboard-graph.png" alt="Dashboard: the six agents and the live event feed" width="820">
</p>
<p align="center">
  <img src="track_1a/docs/assets/dashboard-gap.png" alt="Dashboard: language gap of the 8B run, 41 hypotheses by language" width="820">
</p>

## Run it

```bash
cd track_1a
make run          # Docker, no GPU: replays the canonical run and checks the five findings
make test         # unit tests
make dashboard    # live dashboard on http://127.0.0.1:8765
```

`make run` replays run `20261016-172309-1f71` from `data/llm_cache/`, validates every findings
file, rebuilds the four text findings from the run data in `data/runs/` and recomputes the speech
finding's numbers from its per-clip scores, fails on any difference with `findings/` and prints the
report's summary table.

The report and its figures:

```bash
cd track_1a
python3 scripts/build_report.py --md technical_report.md --out Star-rust_Report.pdf
```

`scripts/report_figures.py` rebuilds `docs/figures/` from the run logs (command in its docstring).

Against live models (vLLM serving Apertus, see [`track_1a/infra/runpod`](track_1a/infra/runpod)):

```bash
LLM_BASE_URL=http://127.0.0.1:8000/v1 RED_LLM_BASE_URL=http://127.0.0.1:8002/v1 make dev
```

With no endpoint and no cache, the harness falls back to a clearly labelled MOCK backend whose output
is never treated as a finding.

## Repository map

| Path | What it is |
|---|---|
| [`track_1a/src/redteam/`](track_1a/src/redteam) | The harness: agents, graph, cache, judge, control, speech probe, dashboard server |
| [`track_1a/src/redteam/hypotheses/`](track_1a/src/redteam/hypotheses) | Sourced hypotheses and attack strategies |
| [`track_1a/findings/`](track_1a/findings) | Submitted findings (schema-valid; not yet human-reviewed) |
| [`track_1a/technical_report.md`](track_1a/technical_report.md) | The report; [`Star-rust_Report.pdf`](track_1a/Star-rust_Report.pdf) is built from it |
| [`track_1a/data/llm_cache/`](track_1a/data/llm_cache) | Recorded model calls, packed in one file, that make the replay possible |
| [`track_1a/data/runs/`](track_1a/data/runs) | Event logs, controls and per-clip speech scores (no SwissDial text) behind the findings and figures |
| [`track_1a/web/`](track_1a/web) | Dashboard and judge-review page |
| [`track_1a/scripts/`](track_1a/scripts) | Report figures, `numbers.json` and the PDF build |
| [`track_1a/infra/runpod/`](track_1a/infra/runpod) | Serving Apertus 8B and 70B with vLLM on a GPU pod, batch scripts |
| [`track_1a/docs/`](track_1a/docs) | Figures, harness guide, roadmap |
| [`track_1a/README.md`](track_1a/README.md) | The official challenge description |

## Team Star-rust

Peter Dike (lead: harness and findings) · Yaseen (infrastructure and packaging) · Nik (UI/UX)

How we branch, review and merge: [`CONTRIBUTING.md`](CONTRIBUTING.md).
Who does what until submission: [`track_1a/docs/ROADMAP.md`](track_1a/docs/ROADMAP.md).

## Licences

Code: Apache-2.0 ([`LICENSE`](LICENSE)). Findings: CDLA-Permissive-2.0
([`track_1a/findings/LICENSE`](track_1a/findings/LICENSE)). The SwissDial audio used by
the speech probe is CC BY-NC 4.0 and is **not** part of this repository.
