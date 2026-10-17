"""Send a wav clip to Apertus v1.5 (vLLM) as an OpenAI-style input_audio part.

The model wants mono 24 kHz audio. Convert first if needed:
    ffmpeg -i in.wav -ac 1 -ar 24000 -sample_fmt s16 out.wav
"""
import base64
import json
import sys
import time
import urllib.error
import urllib.request
import wave
from io import BytesIO

DEFAULT_INSTRUCTION = (
    "Translate this Swiss German audio into Standard German. Output only the translation."
)


def check_format(wav_bytes):
    with wave.open(BytesIO(wav_bytes)) as w:
        if w.getnchannels() != 1 or w.getframerate() != 24000:
            print(f"warning: {w.getnchannels()} ch / {w.getframerate()} Hz, "
                  "expected mono 24 kHz", file=sys.stderr)


def ask_with_audio(base_url, model, wav_bytes, instruction, max_tokens=256, timeout=120, seed=0):
    content = [
        {"type": "input_audio",
         "input_audio": {"data": base64.b64encode(wav_bytes).decode(), "format": "wav"}},
        {"type": "text", "text": instruction},
    ]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "seed": seed,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.load(resp)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}") from None
    return out["choices"][0]["message"]["content"].strip()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python speech.py clip.wav [instruction]")
    wav = open(sys.argv[1], "rb").read()
    check_format(wav)
    instruction = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_INSTRUCTION
    t0 = time.time()
    answer = ask_with_audio("http://127.0.0.1:8000/v1", "swiss-ai/Apertus-v1.5-8B", wav, instruction)
    print(answer)
    print(f"[{time.time() - t0:.1f}s]", file=sys.stderr)
