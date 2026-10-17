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
from .cache import CacheMiss
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
                **judge_meaning(red, text, clip["gold"])}

    with ThreadPoolExecutor(8) as pool:
        return [r for r in pool.map(one, apertus_clips) if r]


def fmt(row, key, spec):
    # A dash, not 0%, when the judge rated none of the dialect's clips or Whisper has no row.
    value = (row or {}).get(key)
    return "-" if value is None else format(value, spec)


def table(dialects):
    lines = [f"{'dialect':<8}{'Apertus unrelated':>19}{'Whisper unrelated':>19}"
             f"{'Apertus chrF':>14}{'Whisper chrF':>14}"]
    for row in dialects:
        a_row, w_row = row["apertus"], row["whisper"]
        lines.append(f"{row['dialect']:<8}{fmt(a_row, 'unrelated_rate', '.0%'):>19}"
                     f"{fmt(w_row, 'unrelated_rate', '.0%'):>19}"
                     f"{fmt(a_row, 'mean_chrf', '.1f'):>14}{fmt(w_row, 'mean_chrf', '.1f'):>14}")
    return "\n".join(lines)


def connect_judge():
    red = llm_mod.detect()
    backend = getattr(red, "backend", None)
    if backend == "MOCK":
        raise SystemExit("no judge reachable and nothing to replay; a MOCK judge proves nothing")
    if backend == "vllm":
        # With the red-team server down, detect() lets the target judge, and whisper_compare.json
        # does not record which model judged. Point RED_LLM_BASE_URL at the target to mean it.
        llm_mod.require_servers()
    return red


def missed_cache(record):
    return record.get("meaning_error", "").startswith(f"{CacheMiss.__name__}:")


def require_verdicts(records, target):
    """Stop before the write whenever it would replace the recorded verdicts in target with less:
    no transcript matches a scored clip, the judge rated no clip at all (e.g. the tunnel is down),
    or a replay misses the cache. Only a replay raises CacheMiss, and it can never rate a clip it
    has not recorded, so even one miss means the transcripts are not the recorded ones. A live
    partial outage is still written, with its 'unknown' clips counted."""
    if not records:
        raise SystemExit(f"no Whisper transcript matches a scored clip; {target} left as it was")
    missed = [r for r in records if missed_cache(r)]
    if missed:
        raise SystemExit(f"{len(missed)} of {len(records)} Whisper clips are not in the cache "
                         f"({missed[0]['meaning_error']}); {target} left as it was")
    failed = [r for r in records if r["meaning"] == "unknown"]
    if len(failed) == len(records):
        raise SystemExit(f"the judge rated none of the {len(records)} Whisper clips "
                         f"({failed[0]['meaning_error']}); {target} left as it was")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("apertus", type=Path)
    ap.add_argument("whisper", type=Path)
    a = ap.parse_args(argv)
    apertus = json.loads(a.apertus.read_text())
    whisper = json.loads(a.whisper.read_text())
    target = a.apertus.with_name("whisper_compare.json")

    records = score_whisper(apertus["clips"], whisper["transcripts"], connect_judge())
    require_verdicts(records, target)
    rows_w = {r["dialect"]: r for r in summarize(records)}
    rows_a = {r["dialect"]: r for r in apertus["dialects"]}
    out = {"apertus_model": apertus["model"], "whisper_model": whisper["model"],
           "dialects": [{"dialect": d, "apertus": rows_a[d], "whisper": rows_w.get(d)} for d in rows_a],
           "whisper_clips": records}
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False))

    print(table(out["dialects"]))
    unknown = [sum(c.get("meaning") == "unknown" for c in clips)
               for clips in (apertus["clips"], records)]
    print(f"meaning unknown (left out of the rates): Apertus {unknown[0]}, Whisper {unknown[1]}")
    print(f"-> {target}")


if __name__ == "__main__":
    main()
