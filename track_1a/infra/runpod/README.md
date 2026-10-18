# RunPod setup (2 × RTX PRO 6000 Blackwell, 96 GB each)

Note: on this pod `/workspace` lives on the container disk, so a pod reset wipes it. Rerun:

1. `bash install_vllm.sh` (swiss-ai vLLM fork `apertus-1-5-final` + swiss-ai Transformers fork)
2. `hf auth login` (by hand, models are gated)
3. `bash serve_8b.sh` → target `swiss-ai/Apertus-v1.5-8B` on GPU 0, `127.0.0.1:8000`
4. `bash serve_70b_red.sh` → attacker/mutator/judge `onprem-ai/Apertus-v1.5-70B-FP8` on GPU 1, `127.0.0.1:8002`
5. Optional: `bash serve_70b_target.sh` instead of step 3 → the 70B as target on GPU 0, port 8000
   (ungated, so it works without `hf auth login`)
6. From the laptop: `infra/runpod/batches.sh [target70|mitigation|rejudge|all]` (run from
   `track_1a/`). Each batch first asks both ports which model they serve and stops if it is not
   the one the batch needs (the 70B target on 8000, `apertus-70b-fp8` on 8002), so a leftover 8B
   server never gets labelled "70B target". `mitigation` stops if the 70B run has no findings
   files, rather than retesting every hypothesis. `morning` is described below.
7. Speech baseline: `python whisper_baseline.py CLIP_DIR OUT.json --batch 2` on the pod, then
   `PYTHONPATH=src python3 -m redteam.speech_compare <speech results.json> OUT.json` on the laptop.
   The default model loads at the commit the report used; another `--model` loads its main branch
   unless `--revision COMMIT` names one. OUT.json records the commit next to the model.

The serve scripts pass `--revision` and `--tokenizer-revision`, so vLLM loads the weights and chat
template at the commits of the recorded runs of 16 and 17 October, not whatever is on `main` on the
Hub that day. `REVISIONS` in `src/redteam/models.py` stamps those commits on every findings file
rebuilt from the recorded runs, and `whisper_baseline.py`, `technical_report.md` and
`src/redteam/chat_template.json` name them too. Serving another commit therefore means recording new
runs and changing all of these together, never editing a serve script alone.

`VLLM_USE_FLASHINFER_SAMPLER=0` works around FlashInfer's architecture check failing on Blackwell.

Tunnel from the laptop (port 8001 is the baseline's, used only by `morning`):

    ssh -N -L 8000:127.0.0.1:8000 -L 8001:127.0.0.1:8001 -L 8002:127.0.0.1:8002 -p <PORT> root@<IP>

## The morning batch

`batches.sh morning` runs the five experiments of `docs/PREREGISTRATION.md` in one session and
then stops the pod. Before the session, on the laptop:

1. Pin the baseline: set `REVISION` in `serve_baseline.sh` to the `sha` that
   `https://huggingface.co/api/models/Qwen/Qwen2.5-7B-Instruct` reports, and add the same commit to
   `REVISIONS` in `src/redteam/models.py`. The script refuses to serve without it, and `morning`
   stops before any GPU time.
2. Opt in to bank 3: look up each of the four made-up names with its town in a public directory
   such as tel.search.ch and replace any name a real person there carries, then copy
   `src/redteam/invented_persons.json` to `src/redteam/hypotheses/bank3.json` and give its four
   ids `skip` entries in `src/redteam/numeric_facts.json` ("Not a number: ..."), which must list
   every hypothesis in the banks. It stays out of the banks until then, so the canonical run, the
   tests and the numeric scorer are unchanged; `make run` replays the canonical 41 hypotheses
   either way.
3. Commit `docs/PREREGISTRATION.md` as it stands; `morning` refuses to start otherwise.
4. `infra/runpod/batches.sh --dry-run morning` (with `POD_HOST` and `POD_PORT` set) prints every
   command and checks every id list without calling the pod.

On the pod: `bash install_vllm.sh` and `hf auth login` as at the top, and from the laptop
`scp -P <PORT> infra/runpod/*.sh root@<IP>:/workspace/`. Start no model server; with the tunnel
up, run on the laptop:

    POD_HOST=root@<IP> POD_PORT=<PORT> infra/runpod/batches.sh morning

It starts the 70B red-team model on GPU 1 and switches GPU 0, which holds one model of 8B size at
a time, over ssh: the baseline for the second judge (M1), Apertus 8B for M2 to M4, the baseline
again as target (M5). Before each step it checks which model each port serves, and while a
server loads it stops as soon as that server has exited on the pod, with the end of its log. A
step that fails stops the pod as well, so it does not bill until someone looks; `KEEP_POD=1`
keeps it running to rerun the rest by hand, and then `stop_pod.sh` ends it. The recorded runs
took 15 minutes (8B, 41 hypotheses), 27 (70B) and 38 (70B, bank 2), so expect about two hours
with the model loads. Results stay in `runs/`: `rejudge_Qwen_Qwen2.5-7B-Instruct.json` for the
8B and 70B runs, `20261016-172309-1f71/control_neutral.json`, and three new runs.

The baseline is `Qwen/Qwen2.5-7B-Instruct` (`serve_baseline.sh`, GPU 0, port 8001): open weights
under Apache 2.0, ungated, 7.6 billion parameters against Apertus' 8 billion, instruction-tuned,
trained for German, French and Italian among others (not Romansh or Swiss German), and served by
the same vLLM. It comes from another family than Apertus, so it also serves as the second judge
from another family, at the cost that a 7B judge differs from the 70B judge in size as well.

When the batches are done, stop the pod so billing ends (it also stops the model servers):

    scp -P <PORT> infra/runpod/stop_pod.sh root@<IP>:/workspace/ && ssh -p <PORT> root@<IP> 'bash /workspace/stop_pod.sh'

`/workspace` is not persistent on this pod: everything the report needs is cached on the laptop.
A live run stores each model call as its own file in `data/llm_cache/`; before committing, fold
them into the one compressed pack with `python3 scripts/pack_cache.py --prune` (from `track_1a/`),
and copy a run the findings rest on into `data/runs/`.
