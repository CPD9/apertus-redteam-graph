"""Score a Whisper baseline on the same SwissDial clips as an Apertus speech run, with the same chrF
and the same meaning judge, and print both side by side per dialect.

    PYTHONPATH=src python -m redteam.speech_compare APERTUS_RESULTS.json WHISPER.json
"""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm as llm_mod
from .speech_eval import chrf, is_hallucinated, judge_meaning, summarize


def score_whisper(apertus_clips, transcripts, red):
    def one(clip):
        key = f"ch_{clip['dialect']}_{clip['sentence_id']:04d}"
        text = transcripts.get(key)
        if text is None or "chrf" not in clip:
            return None
        score = chrf(text, clip["gold"])
        return {"dialect": clip["dialect"], "sentence_id": clip["sentence_id"], "gold": clip["gold"],
                "output": text, "chrf": round(score, 2), "hallucinated": is_hallucinated(score, text),
                "meaning": judge_meaning(red, text, clip["gold"])}

    with ThreadPoolExecutor(8) as pool:
        return [r for r in pool.map(one, apertus_clips) if r]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apertus", type=Path)
    ap.add_argument("whisper", type=Path)
    a = ap.parse_args(argv)
    apertus = json.loads(a.apertus.read_text())
    whisper = json.loads(a.whisper.read_text())

    records = score_whisper(apertus["clips"], whisper["transcripts"], llm_mod.detect())
    rows_w = {r["dialect"]: r for r in summarize(records)}
    rows_a = {r["dialect"]: r for r in apertus["dialects"]}
    out = {"apertus_model": apertus["model"], "whisper_model": whisper["model"],
           "dialects": [{"dialect": d, "apertus": rows_a[d], "whisper": rows_w.get(d)} for d in rows_a],
           "whisper_clips": records}
    target = a.apertus.with_name("whisper_compare.json")
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(f"{'dialect':<8}{'Apertus unrelated':>19}{'Whisper unrelated':>19}{'Apertus chrF':>14}{'Whisper chrF':>14}")
    for row in out["dialects"]:
        a_row, w_row = row["apertus"], row["whisper"] or {}
        print(f"{row['dialect']:<8}{a_row.get('unrelated_rate', 0):>19.0%}{w_row.get('unrelated_rate', 0):>19.0%}"
              f"{a_row['mean_chrf']:>14.1f}{w_row.get('mean_chrf', 0):>14.1f}")
    print(f"-> {target}")


if __name__ == "__main__":
    main()
