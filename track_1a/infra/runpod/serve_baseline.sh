# Baseline on the same items: Qwen2.5-7B-Instruct, an open-weight instruct model of Apertus 8B's
# size from another family (Apache 2.0, ungated, so no `hf auth login`), on GPU 0, port 8001. It is
# also the second judge from another family. GPU 0 holds one model of this size at a time, so
# `batches.sh morning` switches between this script and serve_8b.sh.
. /workspace/venv/bin/activate
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HOME=/workspace/.cache/huggingface CUDA_VISIBLE_DEVICES=0
MODEL=Qwen/Qwen2.5-7B-Instruct
# The commit of the weights and chat template, pinned like the Apertus models so a new upload
# cannot change the baseline: the "sha" that huggingface.co/api/models/Qwen/Qwen2.5-7B-Instruct
# reports on the day it is first served, also recorded in REVISIONS in src/redteam/models.py.
REVISION=
if [[ ! $REVISION =~ ^[0-9a-f]{40}$ ]]; then
  echo "pin REVISION in $0 to a commit of $MODEL first" >&2
  exit 1
fi
exec vllm serve "$MODEL" \
  --revision "$REVISION" --tokenizer-revision "$REVISION" \
  --host 127.0.0.1 --port 8001 \
  --gpu-memory-utilization 0.85 \
  --max-model-len 32768
