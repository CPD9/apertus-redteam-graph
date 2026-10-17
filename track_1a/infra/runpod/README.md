# RunPod setup (2 × RTX PRO 6000 Blackwell, 96 GB each)

Note: on this pod `/workspace` lives on the container disk, so a pod reset wipes it. Rerun:

1. `bash install_vllm.sh` (swiss-ai vLLM fork `apertus-1-5-final` + swiss-ai Transformers fork)
2. `hf auth login` (by hand, models are gated)
3. `bash serve_8b.sh` → target `swiss-ai/Apertus-v1.5-8B` on GPU 0, `127.0.0.1:8000`
4. `bash serve_70b_red.sh` → attacker/mutator/judge `onprem-ai/Apertus-v1.5-70B-FP8` on GPU 1, `127.0.0.1:8002`

`VLLM_USE_FLASHINFER_SAMPLER=0` works around FlashInfer's architecture check failing on Blackwell.

Tunnel from the laptop (both ports):

    ssh -N -L 8000:127.0.0.1:8000 -L 8002:127.0.0.1:8002 -p <PORT> root@<IP>
