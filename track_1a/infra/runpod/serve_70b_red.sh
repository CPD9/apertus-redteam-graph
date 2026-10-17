. /workspace/venv/bin/activate
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HOME=/workspace/.cache/huggingface CUDA_VISIBLE_DEVICES=1
# The weights and chat template the report cites (REVISIONS in src/redteam/models.py), not the
# head of main, which a new upload would move.
REVISION=70378c8df951c9f932e0a28f72e0148d868b5f6b
exec vllm serve onprem-ai/Apertus-v1.5-70B-FP8 \
  --revision "$REVISION" --tokenizer-revision "$REVISION" \
  --served-model-name apertus-70b-fp8 \
  --host 127.0.0.1 --port 8002 \
  --chat-template-content-format string \
  --gpu-memory-utilization 0.92 \
  --max-model-len 16384
