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
   files, rather than retesting every hypothesis.
7. Speech baseline: `python whisper_baseline.py CLIP_DIR OUT.json --batch 2` on the pod, then
   `PYTHONPATH=src python3 -m redteam.speech_compare <speech results.json> OUT.json` on the laptop

`VLLM_USE_FLASHINFER_SAMPLER=0` works around FlashInfer's architecture check failing on Blackwell.

Tunnel from the laptop (both ports):

    ssh -N -L 8000:127.0.0.1:8000 -L 8002:127.0.0.1:8002 -p <PORT> root@<IP>

When the batches are done, stop the pod so billing ends (it also stops the model servers):

    scp -P <PORT> infra/runpod/stop_pod.sh root@<IP>:/workspace/ && ssh -p <PORT> root@<IP> 'bash /workspace/stop_pod.sh'

`/workspace` is not persistent on this pod: everything the report needs is cached on the laptop.
A live run stores each model call as its own file in `data/llm_cache/`; before committing, fold
them into the one compressed pack with `python3 scripts/pack_cache.py --prune` (from `track_1a/`),
and copy a run the findings rest on into `data/runs/`.
