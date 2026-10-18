"""The speech run as the repository ships it, and the speech finding rebuilt from it.

    PYTHONPATH=src python3 -m redteam.speech_scores runs/speech/<run>   # writes its scores.json

SwissDial (CC BY-NC 4.0) is not redistributed, so data/runs/speech/<run>/scores.json keeps the
run's models, instruction and temperature and each clip's dialect, sentence id, verdict and chrF,
and no reference sentence or model output. speech_finding.build reads a whole run; rebuild() gives
it these scores with the outputs the finding itself quotes as the only model text. Every field of
the rebuilt finding then follows from the scores, except those quoted outputs.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import paths, speech_finding, walkthrough

SPEECH = paths.SHIPPED / "speech"
SCORED = ("dialect", "sentence_id", "chrf", "meaning")
SETTINGS = ("model", "judge", "instruction", "temperature")
CLIP = re.compile(r"\[audio: (SwissDial (\w+) sentence (\d+))\] ")
MARK = "\uffff"  # stands for the output while a walkthrough is split around it


def scores(results: dict, compare: dict, run_id: str) -> dict:
    """The per-clip scores of a speech run, without SwissDial's sentences or either output."""
    def kept(clips):
        return [{key: clip[key] for key in SCORED if key in clip} for clip in clips]

    return {"run_id": run_id, **{key: results[key] for key in SETTINGS},
            "whisper_model": compare["whisper_model"], "apertus": kept(results["clips"]),
            "whisper": kept(compare["whisper_clips"])}


def path_of(run_id: str) -> Path:
    return SPEECH / run_id / "scores.json"


def write(run_dir: Path) -> Path:
    results, compare = (json.loads((run_dir / name).read_text())
                        for name in ("results.json", "whisper_compare.json"))
    path = path_of(run_dir.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scores(results, compare, run_dir.name), indent=1) + "\n")
    return path


def quoted(finding: dict, instruction: str) -> dict[tuple[str, int], str]:
    """The output each walkthrough of the finding shows, by dialect and sentence id. A walkthrough
    not in the form speech_finding writes is left out, so the rebuild shows the difference."""
    outputs = {}
    for shown in finding["apertus_response_walkthroughs"]:
        if not (clip := CLIP.search(shown)):
            continue
        head, tail = walkthrough.render(f"[audio: {clip[1]}] {instruction}", MARK).split(MARK)
        if shown.startswith(head) and shown.endswith(tail):
            outputs[clip[2], int(clip[3])] = shown[len(head):len(shown) - len(tail)]
    return outputs


def as_recorded(s: dict, outputs: dict[tuple[str, int], str]) -> tuple[dict, dict]:
    """The results.json and whisper_compare.json that speech_finding.build reads, from scores:
    only the given outputs, and no reference sentence (so there is nothing to leak)."""
    apertus = [{**c, "output": outputs.get((c["dialect"], c["sentence_id"]), ""), "gold": ""}
               for c in s["apertus"]]
    results = {**{key: s[key] for key in SETTINGS}, "clips": apertus}
    return results, {"whisper_model": s["whisper_model"],
                     "whisper_clips": [{**c, "gold": ""} for c in s["whisper"]]}


def rebuild(finding: dict) -> dict:
    """The speech finding as speech_finding builds it from its run's scores and its own quotes."""
    run_id = finding["model"]["parameters"]["harness_run_id"]
    s = json.loads(path_of(run_id).read_text())
    return speech_finding.build(*as_recorded(s, quoted(finding, s["instruction"])), run_id)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Write the per-clip scores of a speech run to "
                                             "data/runs/speech/<run>/scores.json.")
    ap.add_argument("run", type=Path, help="runs/speech/<run> with results.json and "
                                           "whisper_compare.json")
    print(f"wrote {write(ap.parse_args(argv).run)}")


if __name__ == "__main__":
    main()
