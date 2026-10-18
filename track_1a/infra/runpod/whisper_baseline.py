"""Transcribe SwissDial clips with a Swiss German Whisper model, as a baseline for Apertus audio.

Runs on the GPU pod inside /workspace/venv:
    python whisper_baseline.py CLIP_DIR OUT.json [--model MODEL [--revision COMMIT]]
CLIP_DIR holds <dialect>/ch_<dialect>_<id>.wav. The default model (MIT) was trained on the Swiss
Parliament Corpus, not on SwissDial, so the comparison is not contaminated. It loads at the commit
the report's baseline ran on; another --model loads its main branch unless --revision names a
commit. OUT.json records the commit used, or null for main.
"""
import argparse
import json
from pathlib import Path

DEFAULT_MODEL = "gcoli/whisper-large-v3-swiss-german-mit"
# REVISIONS in src/redteam/models.py stamps this commit on the speech finding.
PINNED = {DEFAULT_MODEL: "38955e408982fbdd6163f823bc821542b44751a5"}


def parse_args(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("clip_dir", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--revision", help="commit of the --model weights (default: the report's "
                                       "commit for the default model, main for any other)")
    ap.add_argument("--batch", type=int, default=16, help="lower it when sharing the GPU")
    a = ap.parse_args(argv)
    a.revision = a.revision or PINNED.get(a.model)
    return a


def main():
    a = parse_args()
    # Only the pod's venv has torch and transformers; importing them here keeps parse_args
    # testable on the laptop.
    import torch
    from transformers import pipeline

    asr = pipeline("automatic-speech-recognition", model=a.model, revision=a.revision,
                   torch_dtype=torch.float16, device="cuda:0")
    wavs = sorted(a.clip_dir.glob("*/ch_*_*.wav"))
    texts = asr([str(w) for w in wavs], batch_size=a.batch,
                generate_kwargs={"language": "german", "task": "transcribe"})
    out = {w.stem: t["text"].strip() for w, t in zip(wavs, texts)}
    record = {"model": a.model, "revision": a.revision, "transcripts": out}
    a.out.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    print(f"{len(out)} clips -> {a.out}")


if __name__ == "__main__":
    main()
