. /workspace/venv/bin/activate
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HOME=/workspace/.cache/huggingface CUDA_VISIBLE_DEVICES=0
# The weights and chat template the report cites (REVISIONS in src/redteam/models.py), not the
# head of main, which a new upload would move.
REVISION=ef4bbc54d6fe658bc782280ff9f3b53a10a9758f
exec vllm serve swiss-ai/Apertus-v1.5-8B \
  --revision "$REVISION" --tokenizer-revision "$REVISION" \
  --host 127.0.0.1 --port 8000 \
  --chat-template-content-format string \
  --gpu-memory-utilization 0.85 \
  --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser apertus
