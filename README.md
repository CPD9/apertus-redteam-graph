# Apertus Red-Team Graph

**Same question, six Swiss languages, different truths.**
A self-hosted harness in which Apertus 70B attacks and judges Apertus, asking every probe in
English, German, Swiss German, French, Italian and Romansh, so that a wrong answer about Swiss
rights is caught as a pattern across languages and seeds, not as an anecdote. Every text and image
model call is recorded and replays without a GPU; the speech finding is recomputed from the
per-clip scores that ship (the audio is not in the repository).

Team **Star-rust** · HackApertus 2026 · Track 1A (red-teaming) ·
**[Report (PDF)](track_1a/Star-rust_Report.pdf)** · [Challenge text](track_1a/README.md)

<p align="center">
  <img src="track_1a/docs/assets/agent-loop.svg" alt="Animated agent loop: attacker, mutator, target, judge, verifier, scribe" width="900">
</p>

## Five findings

The table `make run` prints at the end, rebuilt from the recorded runs
(`make reproduce` prints it too). Wrong answers count only when the judge rates them as stating the
error, over 6 languages × 3 seeds; the speech finding counts clips translated into something
unrelated to what was said.

| Finding | Target | Wrong answers (95% CI) | English / worst | Asked neutrally | On 70B |
|---|---|---|---|---|---|
| 1. [Apertus confirms false claims about Swiss history, voting rules and literature](track_1a/findings/civic_sycophancy.json) (8 variations) | 8B | 74% (52–92) | 50% / fr, rm 88% | 35% | 39% |
| 2. [Apertus confirms made-up details about a private person](track_1a/findings/private_person_fabrication.json) (1) | 8B | 83% (50–100) | 0% / others 100% | 0% | 17% |
| 3. [Apertus gets Swiss emergency numbers, health insurance and alarm sirens wrong](track_1a/findings/safety_knowledge_gaps.json) (4) | 8B | 71% (38–96) | 75% / it 92% | 75% | 46% |
| 4. [Apertus gets Swiss old-age pension rules wrong](track_1a/findings/pension_rules.json) (2) | 8B | 64% (28–89) | 67% / gsw, it 83% | 72% | 56% |
| 5. [Apertus invents what Swiss German speakers said](track_1a/findings/speech_dialect_hallucination.json) (480 clips) | 70B | 48% (36–60) | Basel 32% / Aargau 68% | – | – |

**The language gap.** Over the 40 hypotheses attacked on both models, the share of wrong answers
is lowest in English and highest in Romansh:

| | English | German | Swiss German | French | Italian | Romansh |
|---|---|---|---|---|---|---|
| Apertus 8B | 25% | 31% | 38% | 41% | 36% | **48%** |
| Apertus 70B | **5%** | 19% | 20% | 22% | 27% | **42%** |

Tested over hypotheses and corrected for multiple tests, every language's gap to English holds on
the 70B except German's, and none does on the 8B
([figure and intervals](track_1a/docs/figures/languages_8b_70b.svg)).

## Judging the submission

```bash
cd track_1a
make run          # Docker, no GPU: replays the canonical run, checks and rebuilds the five findings
make crosscheck   # recounts every reported number without the harness's counting code
```

Then read the [report](track_1a/Star-rust_Report.pdf) and the [five findings](track_1a/findings).
How we checked them: an [independent recount](track_1a/docs/audit/crosscheck.md), the
[judge against a numeric scorer](track_1a/docs/audit/calibration.md), [statistics that respect the
design](track_1a/docs/audit/stats.md), [the language of every prompt](track_1a/docs/audit/stimuli.md),
the findings [scored again against the rubric](track_1a/docs/audit/rescore.md), and the next
experiments [registered before they run](track_1a/docs/PREREGISTRATION.md).

What those checks do not settle yet:

- **No human labels.** No one has labelled the judge's decisions or read the machine-translated
  Swiss German and Romansh prompts; the [review page](track_1a/docs/LABELLING.md) is ready.
- **The judge, checked without people.** A second Apertus judge flags 97% of what the main judge
  flags but many corrections too (κ 0.19, on shortened answers). Against the numeric scorer the
  judge counts 59 of 73 wrong-value answers but also 3 of 12 right-value ones (κ 0.47): weaker, and
  no correction of the rates can rest on it.
- **The image probe is not reported**: its judge saw the false claim as typed by the user, though
  it was only in the image.

## Working on it as a teammate

```bash
cd track_1a
make reproduce    # rebuild the five findings and compare them with findings/
make audit        # rerun the audit scripts and rewrite the notes in docs/audit/
make dashboard    # open http://127.0.0.1:8765/review.html to label judge decisions
```

Recipes, with what the output should look like: [reproduce a finding](track_1a/docs/playbooks/reproduce-a-finding.md),
[audit the numbers](track_1a/docs/playbooks/audit-the-numbers.md),
[label the judge](track_1a/docs/playbooks/label-the-judge.md).

## Taking the method further

- **A new model**: point `LLM_BASE_URL` at any OpenAI-compatible server and run the same
  hypotheses: [new-model.md](track_1a/docs/playbooks/new-model.md).
- **A new language or a new domain**: new hypotheses with sourced references, and the languages
  they are asked in: [new-domain.md](track_1a/docs/playbooks/new-domain.md).
- **How the graph works** and every command: [HARNESS.md](track_1a/docs/HARNESS.md). With
  `pip install -e track_1a` (no dependencies), `apertus-redteam` lists the commands from anywhere.

## Repository map

| Path | What it is |
|---|---|
| [`track_1a/src/redteam/`](track_1a/src/redteam) | The harness and its one entry point, `python -m redteam` |
| [`track_1a/src/redteam/hypotheses/`](track_1a/src/redteam/hypotheses) | Hypotheses with sourced references, and attack strategies |
| [`track_1a/src/crosscheck/`](track_1a/src/crosscheck) | The independent recount of every reported number |
| [`track_1a/findings/`](track_1a/findings) | The five submitted findings (schema-valid; not yet human-reviewed) |
| [`track_1a/data/`](track_1a/data) | Recorded runs and model calls that the replay and the findings rest on |
| [`track_1a/docs/`](track_1a/docs) | Audits, figures, playbooks, [roadmap](track_1a/docs/ROADMAP.md) |
| [`track_1a/scripts/`](track_1a/scripts) | Report figures, audit notes and the PDF build |
| [`track_1a/infra/runpod/`](track_1a/infra/runpod) | Serving Apertus 8B and 70B with vLLM on a GPU pod |

## Team Star-rust

Peter Dike (lead: harness and findings) · Yaseen (infrastructure and packaging) · Nik (UI/UX).
How we branch, review and merge: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licences

Code: Apache-2.0 ([`LICENSE`](LICENSE)). Findings: CDLA-Permissive-2.0
([`track_1a/findings/LICENSE`](track_1a/findings/LICENSE)). The SwissDial audio used by the speech
probe is CC BY-NC 4.0 and is **not** part of this repository.
