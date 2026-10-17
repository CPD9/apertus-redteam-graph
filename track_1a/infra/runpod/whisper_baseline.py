"""Transcribe SwissDial clips with a Swiss German Whisper model, as a baseline for Apertus audio.

Runs on the GPU pod inside /workspace/venv:
    python whisper_baseline.py CLIP_DIR OUT.json [--model gcoli/whisper-large-v3-swiss-german-mit]
CLIP_DIR holds <dialect>/ch_<dialect>_<id>.wav. The model (MIT) was trained on the Swiss Parliament
Corpus, not on SwissDial, so the comparison is not contaminated.
"""
import argparse
import json
from pathlib import Path

import torch
from transformers import pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--model", default="gcoli/whisper-large-v3-swiss-german-mit")
    ap.add_argument("--batch", type=int, default=16, help="lower it when sharing the GPU")
    a = ap.parse_args()

    asr = pipeline("automatic-speech-recognition", model=a.model, torch_dtype=torch.float16,
                   device="cuda:0")
    wavs = sorted(a.clip_dir.glob("*/ch_*_*.wav"))
    texts = asr([str(w) for w in wavs], batch_size=a.batch,
                generate_kwargs={"language": "german", "task": "transcribe"})
    out = {w.stem: t["text"].strip() for w, t in zip(wavs, texts)}
    a.out.write_text(json.dumps({"model": a.model, "transcripts": out}, ensure_ascii=False, indent=1))
    print(f"{len(out)} clips -> {a.out}")


if __name__ == "__main__":
    main()
