# Apertus 70B (FP8, ungated community quantisation) as the model under test, GPU 0, port 8000.
. /workspace/venv/bin/activate
export VLLM_USE_FLASHINFER_SAMPLER=0
export HF_HOME=/workspace/.cache/huggingface CUDA_VISIBLE_DEVICES=0
exec vllm serve onprem-ai/Apertus-v1.5-70B-FP8 \
  --served-model-name onprem-ai/Apertus-v1.5-70B-FP8 \
  --host 127.0.0.1 --port 8000 \
  --chat-template-content-format string \
  --gpu-memory-utilization 0.92 \
  --max-model-len 16384
