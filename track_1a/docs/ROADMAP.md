# Roadmap to submission

Deadline: Monday 19 October. Feature freeze: Sunday 23:00. Mentors on site: Sunday 18 October.

## The five findings (`findings/`)

1. **Civic sycophancy**: false claims about voting rules, history and literature confirmed in 74% of
   8B answers, against 35% wrong when asked neutrally.
2. **Private person**: a stranger's employer and address confirmed in every language but English.
3. **Safety knowledge gaps**: poison number, helplines, sirens, deductibles; wrong even when asked neutrally.
4. **Pensions**: AHV 21 transition rules and contribution start, wrong on both model sizes.
5. **Speech**: Apertus 70B's audio input invents what Swiss German speakers said in 48% of 480
   clips; a Swiss German Whisper in 1%.

## Peter: harness and findings

- [ ] Label 50 judge decisions on the review page (judge–human agreement for the report)
- [ ] Hand-check the top candidates of each finding; promote the five to `findings/`
- [x] Stricter speech judge (same meaning / partial / unrelated)
- [x] Rerun the top findings with Apertus 70B as target (breadth: both sizes)
- [x] Technical report, 6 pages, every measured number from a recorded run (draft; numbers audited)
- [ ] Mentor sessions on Sunday (judge trust, statistics, attack diversity)

## Yaseen: infrastructure and packaging (`infra/*`, `fix/*`)

- [x] Get CI green on the first PR (tests, cache replay, schema check, `make run` in Docker)
- [ ] One-command pod bootstrap: `infra/runpod/bootstrap.sh` (install, login hint, both servers, health check)
- [ ] `make run` from a clean clone on a machine that has never seen the project; fix whatever breaks
- [ ] Keep the Docker image small and the cache in `data/` under 100 MB
- [ ] Review every `ml/*` PR for readability and tests

## Nik: UI/UX (`web/*`)

The dashboard works but reads like a log viewer. Goal: someone who has never seen it understands a
finding in ten seconds.

- [ ] **Findings view, redesigned**: one sentence per finding in plain language ("Apertus confirms a
      wrong signature count"), the six-language strip as the hero, the evidence quote and the correct
      answer side by side, judge text collapsed behind "details"
- [ ] **Language-gap overview**: one heatmap, hypotheses × languages, sorted by gap; this is our
      headline figure for the report too
- [ ] **Review page polish**: big tap targets, clear progress, agreement shown in words, not just kappa
- [ ] Consistent type scale, spacing and colour; light and dark; works at laptop width
- [ ] Screenshots for the README and report once the redesign lands

## Definition of done for every PR

Green CI, one review, squash-merge, branch deleted. See [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
