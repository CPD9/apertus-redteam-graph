# RunPod setup (2 × RTX PRO 6000 Blackwell, 96 GB each)

Note: on this pod `/workspace` lives on the container disk, so a pod reset wipes it. Rerun:

1. `bash install_vllm.sh` (swiss-ai vLLM fork `apertus-1-5-final` + swiss-ai Transformers fork)
2. `hf auth login` (by hand, models are gated)
3. `bash serve_8b.sh` → target `swiss-ai/Apertus-v1.5-8B` on GPU 0, `127.0.0.1:8000`
4. `bash serve_70b_red.sh` → attacker/mutator/judge `onprem-ai/Apertus-v1.5-70B-FP8` on GPU 1, `127.0.0.1:8002`
5. Optional: `bash serve_70b_target.sh` instead of step 3 → the 70B as target on GPU 0, port 8000
   (ungated, so it works without `hf auth login`)
6. From the laptop: `infra/runpod/batches.sh [target70|mitigation|rejudge]` (run from `track_1a/`)
7. Speech baseline: `python whisper_baseline.py CLIP_DIR OUT.json --batch 2` on the pod, then
   `PYTHONPATH=src python3 -m redteam.speech_compare <speech results.json> OUT.json` on the laptop

`VLLM_USE_FLASHINFER_SAMPLER=0` works around FlashInfer's architecture check failing on Blackwell.

Tunnel from the laptop (both ports):

    ssh -N -L 8000:127.0.0.1:8000 -L 8002:127.0.0.1:8002 -p <PORT> root@<IP>

When the batches are done, stop the pod so billing ends (it also stops the model servers):

    scp -P <PORT> infra/runpod/stop_pod.sh root@<IP>:/workspace/ && ssh -p <PORT> root@<IP> 'bash /workspace/stop_pod.sh'

`/workspace` is not persistent on this pod: everything the report needs is cached on the laptop.
