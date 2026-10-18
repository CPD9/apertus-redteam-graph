# Audit the numbers

Every number in the findings, the report and `docs/figures/numbers.json` can be derived twice: by
the harness, and by `src/crosscheck/`, which shares with it only the code that finds a recorded
reply (the cache reader, the judge prompts and the run paths). The audit notes in `docs/audit/` are
written by scripts from their JSON, except `crosscheck.md`, which explains the recount by hand.

1. Start in the project, with the code on the path:

   ```bash
   cd track_1a
   export PYTHONPATH=src
   ```

2. Recount everything without the harness's counting code (a few seconds):

   ```bash
   python3 -m redteam crosscheck
   ```

   It opens with the total, then a table of checks per section, lists every check, and must end
   in `0 differ`:

   ```
   1746 checks against the recorded runs: 0 differ.

   section                      checks  differ
   recorded runs                     9       0
   findings/*.json                 590       0
   ...
   1746 checks, 0 differ
   ```

   `python3 -m redteam crosscheck --diffs` prints only the summary and what differs.

3. Rerun the audit scripts and rewrite the notes (about a minute):

   ```bash
   python3 -m redteam audit
   git status docs/audit
   ```

   It runs the numeric scorer, the judge calibration, the statistics, the stimulus language
   check, the cross-check (printing only what differs) and the re-scoring of the findings, in that
   order, and stops at the first that fails. The last line is the re-scoring's check:

   ```
   rescore.json: 62 cited values and counts hold, 18 rewrites fit their findings
   ```

   `git status` should show nothing changed: the notes in the repository are what the data gives.

4. Redraw the report's figures and their numbers, then build the PDF (needs Chrome or Chromium):

   ```bash
   python3 -m redteam figures
   python3 -m redteam report
   ```

   `figures` prints a `wrote` line for each figure and for `numbers.json`; again
   `git status docs/figures` should show nothing changed.
