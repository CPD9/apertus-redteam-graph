# Roadmap to submission

Deadline: Monday 19 October. Feature freeze: Sunday 23:00. Mentors on site: Sunday 18 October.

## The five findings we are building towards

1. **Civic sycophancy**: Apertus confirms false claims about direct democracy it answers correctly when asked neutrally.
2. **History rewritten on request**: women's suffrage (wrong 100% with a premise, 6% without).
3. **Invented personal data in dialect**: details about a private person; English declines.
4. **Safety-critical knowledge gaps**: poison number, 911 confirmed in French and Romansh, deductibles with US terms.
5. **Speech**: invented content from Swiss German audio (Valais, Lucerne worst).

## Peter: harness and findings

- [ ] Label 50 judge decisions on the review page (judge–human agreement for the report)
- [ ] Hand-check the top candidates of each finding; promote the five to `findings/`
- [ ] Stricter speech judge (same meaning / partial / unrelated)
- [ ] Rerun the top findings with Apertus 70B as target (breadth: both sizes)
- [ ] Technical report, 6 pages, every number from a recorded run
- [ ] Mentor sessions on Sunday (judge trust, statistics, attack diversity)

## Yaseen: infrastructure and packaging (`infra/*`, `fix/*`)

- [ ] Get CI green on the first PR (tests, cache replay, schema check, `make run` in Docker)
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
