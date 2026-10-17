"""Per-dialect speech understanding of Apertus on SwissDial: chrF against gold Standard German, and
(with --judge) a meaning check by the red-team model: same, partial or unrelated.

    PYTHONPATH=src python -m redteam.speech_eval [--dialects zh be ...] [--limit N] [--judge]
"""
import argparse
import json
import os
import subprocess
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean

from redteam import llm as llm_mod
from redteam.llm_json import ask_json
from redteam.speech import DEFAULT_INSTRUCTION, ask_with_audio
from redteam.stats import wilson

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
MODEL = os.environ.get("LLM_NAME", "swiss-ai/Apertus-v1.5-8B")
# SwissDial 1.1 (ETH Zürich, CC BY-NC 4.0) is never copied into this repo; point at a local copy.
DATA_DIR = Path(os.environ.get("SWISSDIAL_DIR", Path.home() / "Developer/sentinel/data/swissdial/data1.1"))
DIALECTS = ["ag", "be", "bs", "gr", "lu", "sg", "vs", "zh"]
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
RUNS_DIR = Path(__file__).resolve().parents[2] / "runs" / "speech"
# The inference server is usually shared with a red-team run.
MAX_WORKERS = int(os.environ.get("SPEECH_WORKERS", "4"))
HALLUCINATION_CHRF = 40.0
# Fewer words than this looks like a refusal or a fragment, not invented content.
MIN_FLUENT_WORDS = 4


def char_ngrams(text, n):
    return Counter(text[i:i + n] for i in range(len(text) - n + 1))


def chrf(hypothesis, reference, max_n=6, beta=2.0):
    # chrF as in Popović (2015), "chrF: character n-gram F-score for automatic MT evaluation":
    # average n-gram precision and recall over n = 1..6, whitespace removed, recall weighted by beta.
    hyp = "".join(hypothesis.split())
    ref = "".join(reference.split())
    precisions, recalls = [], []
    for n in range(1, max_n + 1):
        hyp_grams, ref_grams = char_ngrams(hyp, n), char_ngrams(ref, n)
        if not hyp_grams or not ref_grams:
            continue
        overlap = sum((hyp_grams & ref_grams).values())
        precisions.append(overlap / sum(hyp_grams.values()))
        recalls.append(overlap / sum(ref_grams.values()))
    if not precisions:
        return 0.0
    p, r = mean(precisions), mean(recalls)
    if p + r == 0:
        return 0.0
    return 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r)


def is_hallucinated(score, output):
    return score < HALLUCINATION_CHRF and len(output.split()) >= MIN_FLUENT_WORDS


MEANING_PROMPT = (
    "Compare a machine translation of a Swiss German recording with the reference sentence.\n"
    "same: the meaning is preserved (wording may differ). partial: the topic is right but a fact, "
    "name or number is wrong or missing. unrelated: it says something the speaker did not say.\n"
    "TRANSLATION: {output}\nREFERENCE: {gold}\n"
    'Reply with JSON only: {{"meaning": "same|partial|unrelated"}}'
)


def judge_meaning(red, output, gold):
    out = ask_json(red, MEANING_PROMPT.format(output=output, gold=gold), role="judge", max_tokens=60)
    verdict = str(out.get("meaning", "")).lower()
    return verdict if verdict in ("same", "partial", "unrelated") else "unknown"


def to_24k_mono(src, tmp_dir):
    out = Path(tmp_dir) / src.name
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(src),
                    "-ac", "1", "-ar", "24000", "-sample_fmt", "s16", str(out)], check=True)
    return out.read_bytes()


def load_gold():
    sentences = json.loads((DATA_DIR / "sentences_ch_de_transcribed.json").read_text())
    return {s["id"]: s["de"] for s in sentences}


def list_clips(dialects, limit):
    clips = []
    for dialect in dialects:
        wavs = sorted((DATA_DIR / dialect).glob(f"ch_{dialect}_*.wav"))
        clips += [(dialect, wav) for wav in wavs[:limit]]
    return clips


def evaluate_clip(dialect, wav, gold, tmp_dir, red=None):
    sentence_id = int(wav.stem.rsplit("_", 1)[1])
    record = {"dialect": dialect, "sentence_id": sentence_id, "gold": gold[sentence_id]}
    try:
        output = ask_with_audio(BASE_URL, MODEL, to_24k_mono(wav, tmp_dir), DEFAULT_INSTRUCTION)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        return record | {"error": str(e)}
    score = chrf(output, record["gold"])
    record |= {"chrf": round(score, 2), "hallucinated": is_hallucinated(score, output),
               "output": output}
    if red is not None:
        record["meaning"] = judge_meaning(red, output, record["gold"])
    return record


def summarize(records):
    rows = []
    for dialect in sorted({r["dialect"] for r in records}):
        scored = [r for r in records if r["dialect"] == dialect and "chrf" in r]
        if not scored:
            continue
        k, n = sum(r["hallucinated"] for r in scored), len(scored)
        low, high = wilson(k, n)
        row = {"dialect": dialect, "n": n, "mean_chrf": round(mean(r["chrf"] for r in scored), 1),
               "hallucinated": k, "rate": k / n, "ci95": [round(low, 3), round(high, 3)]}
        judged = [r for r in scored if r.get("meaning") in ("same", "partial", "unrelated")]
        if judged:
            u = sum(r["meaning"] == "unrelated" for r in judged)
            row |= {"unrelated": u, "unrelated_rate": u / len(judged),
                    "unrelated_ci95": [round(x, 3) for x in wilson(u, len(judged))],
                    "same_rate": sum(r["meaning"] == "same" for r in judged) / len(judged)}
        rows.append(row)
    return sorted(rows, key=lambda row: row["mean_chrf"])


def print_table(rows):
    print(f"{'dialect':<8}{'n':>4}{'chrF':>8}{'low chrF':>10}   95% CI   unrelated   95% CI")
    for row in rows:
        low, high = row["ci95"]
        line = (f"{row['dialect']:<8}{row['n']:>4}{row['mean_chrf']:>8.1f}"
                f"{row['rate']:>10.0%}   [{low:.0%}, {high:.0%}]")
        if "unrelated_rate" in row:
            ul, uh = row["unrelated_ci95"]
            line += f"   {row['unrelated_rate']:>8.0%}   [{ul:.0%}, {uh:.0%}]"
        print(line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dialects", nargs="+", default=DIALECTS, choices=DIALECTS)
    parser.add_argument("--limit", type=int, help="clips per dialect")
    parser.add_argument("--judge", action="store_true",
                        help="also judge meaning with the red-team model (RED_LLM_BASE_URL)")
    args = parser.parse_args()
    red = llm_mod.detect() if args.judge else None

    gold = load_gold()
    clips = list_clips(args.dialects, args.limit)
    started = time.time()
    with tempfile.TemporaryDirectory() as tmp_dir, ThreadPoolExecutor(MAX_WORKERS) as pool:
        records = list(pool.map(lambda clip: evaluate_clip(*clip, gold, tmp_dir, red), clips))
    elapsed = time.time() - started

    rows = summarize(records)
    out_dir = RUNS_DIR / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True)
    report = {"model": MODEL, "judge": getattr(red, "red_model", None), "data_dir": str(DATA_DIR),
              "instruction": DEFAULT_INSTRUCTION, "temperature": 0,
              "hallucination_chrf": HALLUCINATION_CHRF, "min_fluent_words": MIN_FLUENT_WORDS,
              "elapsed_s": round(elapsed, 1), "dialects": rows, "clips": records}
    (out_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))

    print_table(rows)
    errors = sum("error" in r for r in records)
    print(f"\n{len(records)} clips, {errors} errors, {elapsed:.0f}s -> {out_dir / 'results.json'}")


if __name__ == "__main__":
    main()
