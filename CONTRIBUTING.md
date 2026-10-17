# Contributing

## Branches

`main` is always runnable and always submittable. Nobody pushes to it directly.

| Prefix | Use |
|---|---|
| `ml/` | harness, judge, hypotheses, findings |
| `infra/` | Docker, RunPod/Exoscale scripts, CI |
| `web/` | dashboard and review page |
| `docs/` | README, report, diagrams |
| `fix/` | a bug fix on any of the above |

Keep branches short-lived (hours, not days): branch from the latest `main`, open a PR early as a
draft, and rebase on `main` before asking for review.

## Commits

Conventional style, imperative, one logical change per commit:

```
feat(judge): only count claims the assistant itself asserts
fix(server): reuse a running dashboard instead of failing on the port
docs(readme): add animated agent loop
```

No secrets, no audio, no model weights, no `runs/` output. `.env` stays local.

## Pull requests

1. CI must be green: unit tests, full cache replay, findings schema check.
2. One approving review from someone who did not write the change.
3. Squash-merge, so `main` reads as one commit per change. Delete the branch afterwards.
4. A PR that changes a prompt (attacker, judge, mutator) must say so: it invalidates part of the
   cache and changes results. Record a new run before merging and link it in the PR.
5. A PR that adds or edits a file in `track_1a/findings/` needs a human-review note for that finding.

## Before you push

```bash
cd track_1a && make test
REDTEAM_BACKEND=replay PYTHONPATH=src python3 -m redteam.run && PYTHONPATH=src python3 -m redteam.check
```

## Code style

Small modules and functions, standard library unless there is a strong reason, names over comments,
comments only for the *why*. Refactor when a file grows past ~200 lines. No dead code.
