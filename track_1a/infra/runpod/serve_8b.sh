. /workspace/venv/bin/activate
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HOME=/workspace/.cache/huggingface CUDA_VISIBLE_DEVICES=0
exec vllm serve swiss-ai/Apertus-v1.5-8B \
  --host 127.0.0.1 --port 8000 \
  --chat-template-content-format string \
  --gpu-memory-utilization 0.85 \
  --max-model-len 32768 \
  --enable-auto-tool-choice --tool-call-parser apertus
