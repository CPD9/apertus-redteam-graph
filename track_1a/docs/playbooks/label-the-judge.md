# Label the judge

Every reported rate rests on the judge (Apertus 70B). This is how people check it: blind labels on
60 of its decisions, and native speakers' ratings of the Swiss German and Romansh prompts. No one
has labelled yet. The keys, the rules for labelling blind and what counts as a yes are in the
codebook, [`../LABELLING.md`](../LABELLING.md); read it first.

1. Start the dashboard:

   ```bash
   cd track_1a
   make dashboard
   ```

   It prints `dashboard: http://127.0.0.1:8765`, or that one is already running.

2. Open http://127.0.0.1:8765/review.html, type your name and pick a task: **Check the judge**
   or the language check. Labels go to `data/labels/` as you make them.

3. When you are done, ask for the reveal on the page. It shows where you and the judge differ and
   ends labelling under your name.

4. See what the labels say:

   ```bash
   PYTHONPATH=src python3 -m redteam labels
   ```

   Before anyone has labelled, it says so:

   ```
   No human labels yet. Label the 60 answers on /review.html (make dashboard); this report then fills in by itself.
   ```

   Afterwards it prints agreement with the judge per language and per labeller as JSON.
