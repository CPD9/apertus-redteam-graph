"""The speech figure: how often Apertus and a Swiss German Whisper turn a SwissDial clip into a
translation unrelated to what was said, per dialect and over all dialects.

A speech run folder holds either scores.json, the per-clip verdicts shipped in data/runs/speech/
without any SwissDial text, or the results.json of redteam.speech_eval and the whisper_compare.json
of redteam.speech_compare that a run writes to runs/speech/.

The 480 clips are 8 speakers, one per dialect, reading the same 60 sentences, so they are not
independent: the interval over all dialects resamples dialects and sentences
(speech_finding.clustered, as the finding does); each dialect keeps its Wilson interval.
"""
from __future__ import annotations

import json

from report_charts import BLUE, RED, bar_chart, count_label
from report_runs import Skip, same_model

from redteam.speech_finding import DIALECTS, DRAWS, SEED, RATED, clustered, judged, rates


def read_clips(folder):
    """The run's models and judge, and the judged clips of Apertus and of Whisper."""
    if (folder / "scores.json").is_file():
        scores = json.loads((folder / "scores.json").read_text())
        meta = {key: scores[key] for key in ("model", "judge", "whisper_model")}
        return meta, scores["apertus"], scores["whisper"]
    paths = [folder / "results.json", folder / "whisper_compare.json"]
    if missing := [p.name for p in paths if not p.is_file()]:
        raise Skip(f"no scores.json, and no {' or '.join(missing)} in {folder}")
    results, compare = (json.loads(p.read_text()) for p in paths)
    meta = {"model": results["model"], "judge": results["judge"],
            "whisper_model": compare["whisper_model"]}
    return meta, results["clips"], compare["whisper_clips"]


def overall(clips):
    """The share of all clips judged unrelated, with the cluster interval as its ci95."""
    share = judged(clips).brief()
    return share | {"wilson_ci95": share["ci95"], "ci95": [round(x, 3) for x in clustered(clips)]}


def unrelated_everywhere(clips):
    """SwissDial ids of the sentences judged unrelated in every dialect."""
    dialects = {c["dialect"] for c in clips}
    verdicts = {}
    for c in clips:
        if c.get("meaning") in RATED:
            verdicts.setdefault(c["sentence_id"], {})[c["dialect"]] = c["meaning"]
    return sorted(s for s, by_dialect in verdicts.items()
                  if by_dialect.keys() == dialects and set(by_dialect.values()) == {"unrelated"})


def speech_dialects(folder):
    meta, apertus, whisper = read_clips(folder)
    if not judged(apertus).n:
        raise Skip(f"no clip in {folder} has a judged meaning (speech_eval --judge)")
    shares = rates(apertus, whisper)  # dialect -> (Apertus, Whisper), most unrelated first
    del shares["all"]
    table = [{"dialect": d, "name": DIALECTS.get(d, d), "apertus": a.brief(),
              "whisper": w.brief()} for d, (a, w) in shares.items()]
    pooled = {"apertus": overall(apertus), "whisper": overall(whisper)}
    model = meta["model"].rsplit("/", 1)[-1]
    rows = [(f"{r['name']} ({r['dialect'].upper()})", [r["apertus"], r["whisper"]], None)
            for r in table] + [("All dialects", [pooled["apertus"], pooled["whisper"]], None)]
    own = ", the model that translated" if same_model(meta["judge"], meta["model"]) else ""
    note = (f"Share of translations judged unrelated to what was said, "
            f"{count_label([r['apertus']['n'] for r in table], 'clips per dialect')}, one "
            "speaker each. Whiskers: 95% Wilson CI per dialect; for all dialects, a two-way "
            f"cluster bootstrap over dialects and sentences, as the clips are {len(table)} "
            f"speakers reading the same sentences. Translated by {model} and "
            f"{meta['whisper_model']}, both judged by {meta['judge']}{own}.")
    svg = bar_chart(rows, [("Apertus (audio input)", RED), ("Swiss German Whisper", BLUE)], note,
                    f"Unrelated translations of Swiss German speech per dialect, {model} and a "
                    "Swiss German Whisper", total=True)
    method = f"two-way cluster bootstrap over dialects and sentences, {DRAWS} draws, seed {SEED}"
    return svg, {"folder": str(folder), **meta, "rows": table, "all": pooled,
                 "all_ci95_method": method,
                 "unrelated_in_every_dialect": unrelated_everywhere(apertus)}
